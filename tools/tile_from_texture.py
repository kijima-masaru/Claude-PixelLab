#!/usr/bin/env python3
"""自作画像から 32px の Wang タイルセットを起こす。**API を使わない。**

    python tools/tile_from_texture.py --project iwato \
        --source "refs/screenshot.png" \
        --region 430,400,170,70 --region 660,370,170,60 --region 830,370,170,60 \
        --name tile_asphalt_curb --out _work/tile_asphalt_curb

生成 API に7回投げて一度も届かなかった水準に、この経路は一度で届いた。
**難しいのは16枚を作ることではなく、素材そのものだった。**
16枚の角の組み合わせは、2つの素材と角マスクがあれば合成できる。

工程は6つ。詳細は docs/PILOT_FINDINGS.md の第10〜12節。

  1. 遠近の補正   斑の自己相関長を縦横で比べ、その比だけ縦に伸ばす。
                  **画面ごとに推定する。** カメラの俯角は画面ごとに違う
  2. ひびの除去   ひびは素材ではなく特徴である（第10節）。
                  細い暗線だけをモルフォロジー的に埋め、斑は残す
  3. 窓の選別     目地・白線のような長い直線を含む窓を避ける
  4. コントラスト **等倍で焼くと迷彩柄になる。** 画面の見え方には
                  3Dのライティングが含まれているため、半分に落とす（第11節）
  5. パレット吸着 CIE Lab で測る。重み付き RGB は灰色を紫にする（第12節）
  6. 16枚の合成   角の値を双線形で補間して upper 領域を作り、
                  境界に縁石を描く

**出力は tools/assemble_tileset.py がそのまま読める形式である。**

参照画像ガードとの関係:
    このツールは API を呼ばない。refs/ を入力にしてもよい。
    ただし**出力を PixelLab の参照画像として送るには、
    自作物マニフェストへの登録が要る。** 登録なしでは送信ガードが止める。
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402
from lib import imageops  # noqa: E402

try:
    from PIL import Image, ImageFilter
except ImportError:
    sys.exit("Pillow が必要です: python -m pip install -r requirements.txt")


CORNERS = ("NW", "NE", "SW", "SE")


# ---------------------------------------------------------------------------
# 測る
# ---------------------------------------------------------------------------

def luminance(image: Image.Image) -> list:
    """輝度の二次元配列を返す。"""
    rgb = image.convert("RGB")
    px = rgb.load()
    w, h = rgb.size
    return [[0.299 * px[x, y][0] + 0.587 * px[x, y][1] + 0.114 * px[x, y][2]
             for x in range(w)] for y in range(h)]


def _autocorr(grid: list, dx: int, dy: int) -> float:
    h, w = len(grid), len(grid[0])
    mean = sum(sum(row) for row in grid) / (w * h)
    num = den = 0.0
    for y in range(h - dy):
        for x in range(w - dx):
            a = grid[y][x] - mean
            num += a * (grid[y + dy][x + dx] - mean)
            den += a * a
    return num / den if den else 0.0


def correlation_length(grid: list, axis: str, limit: int = 14) -> float:
    """自己相関が 1/e まで落ちるずらし量。斑の大きさの指標。"""
    for d in range(1, limit + 1):
        value = _autocorr(grid, d, 0) if axis == "x" else _autocorr(grid, 0, d)
        if value < 1 / math.e:
            return d - 0.5
    return float(limit)


def estimate_stretch(image: Image.Image) -> float:
    """縦にどれだけ伸ばせば正射影に近づくか。

    地面の斑は本来等方的である。したがって**縦横の相関長の比が、
    そのまま透視投影による縦圧縮の逆数になる。** 画面の幾何を
    測る必要がない。

    相関長は数画素しかないため**精度は粗い**。実測では同じ画面でも
    手前 2.33 / 中景 1.67 と幅が出た（手前ほど圧縮が強いのは
    透視投影として正しい）。
    """
    grid = luminance(image)
    return correlation_length(grid, "x") / max(correlation_length(grid, "y"), 0.5)


def roughness(image: Image.Image) -> float:
    """局所平均からの平均絶対偏差。3x3。**目標は 3.5〜6.0**（第11節）。"""
    grid = luminance(image)
    h, w = len(grid), len(grid[0])
    total = count = 0.0
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            mean = sum(grid[y + dy][x + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)) / 9.0
            total += abs(grid[y][x] - mean)
            count += 1
    return total / count if count else 0.0


def periodicity(image: Image.Image) -> float:
    """トーラス上での自己相関の最大値。**目標は 0.75 以下**（第11節）。"""
    grid = luminance(image)
    h, w = len(grid), len(grid[0])
    mean = sum(sum(row) for row in grid) / (w * h)
    dev = [[grid[y][x] - mean for x in range(w)] for y in range(h)]
    base = sum(v * v for row in dev for v in row)
    if not base:
        return 0.0
    best = 0.0
    for dy in range(h):
        for dx in range(w):
            if dx == 0 and dy == 0:
                continue
            s = sum(dev[y][x] * dev[(y + dy) % h][(x + dx) % w]
                    for y in range(h) for x in range(w))
            best = max(best, s / base)
    return best


# ---------------------------------------------------------------------------
# 直す
# ---------------------------------------------------------------------------

def heal_cracks(image: Image.Image, threshold: float = 10.0, radius: int = 3) -> tuple:
    """細い暗線（ひび・目地）だけを消す。斑は残す。

    **ひびは素材ではなく特徴であり、タイルに焼くと全面へ反復する**（第10節）。
    かといって「ひびを含む窓を捨てる」と素材が枯れる。ゆえに消す。

    最大値フィルタ（膨張）は radius 未満の暗い細線を消し、
    最小値フィルタ（収縮）が斑の大きさを戻す。この閉じ演算の結果より
    元画像が threshold 以上暗い画素だけを差し替える。
    **斑は radius より太いので残る。**

    radius を上げすぎると斑まで食う。実測（自作ゲームの舗装）:

        radius=3  除去 10.0%  ざらつき 5.18  ← 目標帯（3.5〜6.0）の内側
        radius=5  除去 28.2%  ざらつき 2.76  ← 帯を下回る。斑を消しすぎ

    **3 を既定とする。**
    """
    closed = image.convert("RGB").filter(ImageFilter.MaxFilter(radius)) \
                                 .filter(ImageFilter.MinFilter(radius))
    src, dst = image.convert("RGB").load(), closed.load()
    out = image.convert("RGB").copy()
    put = out.load()
    healed = 0
    for y in range(image.size[1]):
        for x in range(image.size[0]):
            a, b = src[x, y], dst[x, y]
            la = 0.299 * a[0] + 0.587 * a[1] + 0.114 * a[2]
            lb = 0.299 * b[0] + 0.587 * b[1] + 0.114 * b[2]
            if lb - la > threshold:
                put[x, y] = b
                healed += 1
    return out, healed


def compress_contrast(image: Image.Image, factor: float, shift: int = 0) -> Image.Image:
    """平均のまわりでコントラストを圧縮する。

    **画面から測った質感をそのまま焼いてはならない。** 画面の見え方には
    3Dのライティングと法線の陰影が含まれており、テクスチャだけを
    等倍で焼くと迷彩柄になる。実測では ×0.5 で路面になった（第11節）。
    """
    out = image.convert("RGB").copy()
    px = out.load()
    grid = luminance(out)
    mean = sum(sum(row) for row in grid) / (out.size[0] * out.size[1])
    for y in range(out.size[1]):
        for x in range(out.size[0]):
            px[x, y] = tuple(max(0, min(255, int(mean + (v - mean) * factor) + shift))
                             for v in px[x, y])
    return out


def match_means(tiles: list) -> list:
    """タイル間の平均明度を揃える。

    揃えないと、ランダム配置が**継ぎ接ぎ（キルト）**になる。
    継ぎ目が「模様の切れ目」ではなく「明るさの段差」として見えるため。
    """
    means = []
    for tile in tiles:
        grid = luminance(tile)
        means.append(sum(sum(row) for row in grid) / (tile.size[0] * tile.size[1]))
    target = sum(means) / len(means)
    out = []
    for tile, mean in zip(tiles, means):
        delta = target - mean
        image = tile.convert("RGB").copy()
        px = image.load()
        for y in range(image.size[1]):
            for x in range(image.size[0]):
                px[x, y] = tuple(max(0, min(255, int(v + delta))) for v in px[x, y])
        out.append(image)
    return out


# ---------------------------------------------------------------------------
# 選ぶ
# ---------------------------------------------------------------------------

def _straightness(grid: list, x: int, y: int, size: int) -> float:
    """窓の中の「長い直線」の強さ。行平均・列平均の最大段差で測る。"""
    rows = [sum(grid[j][i] for i in range(x, x + size)) / size for j in range(y, y + size)]
    cols = [sum(grid[j][i] for j in range(y, y + size)) / size for i in range(x, x + size)]
    return max(max(abs(rows[k + 1] - rows[k]) for k in range(len(rows) - 1)),
               max(abs(cols[k + 1] - cols[k]) for k in range(len(cols) - 1)))


def pick_windows(source: Image.Image, size: int, count: int, stride: int = 3) -> list:
    """直線的な特徴の少ない窓を、重ならないように選ぶ。

    ひびは heal_cracks が消すので、ここで避けたいのは
    **白線・舗装パネルの目地・落ち影の境目**のような、消せない直線である。
    """
    grid = luminance(source)
    h, w = len(grid), len(grid[0])
    if h < size or w < size:
        raise SystemExit("素材が小さすぎます: %dx%d に %dpx の窓は取れません" % (w, h, size))
    scored = sorted((_straightness(grid, x, y, size), x, y)
                    for y in range(0, h - size + 1, stride)
                    for x in range(0, w - size + 1, stride))
    picked, used = [], []
    for _, x, y in scored:
        if any(abs(x - ux) < size // 2 and abs(y - uy) < size // 2 for ux, uy in used):
            continue
        picked.append(source.crop((x, y, x + size, y + size)))
        used.append((x, y))
        if len(picked) >= count:
            break
    return picked


# ---------------------------------------------------------------------------
# パレット
# ---------------------------------------------------------------------------

def load_palette(path: Path) -> list:
    """.gpl / .hex に加え、PNG からも読む（color_image と同じファイルを使えるように）。"""
    if path.suffix.lower() == ".png":
        image = Image.open(path).convert("RGB")
        return sorted({image.getpixel((x, y))
                       for y in range(image.size[1]) for x in range(image.size[0])})
    return imageops.load_palette(path)


def snap(image: Image.Image, palette: list) -> Image.Image:
    """CIE Lab でパレットへ吸着する（imageops._nearest と同じ距離）。"""
    out = image.convert("RGB").copy()
    px = out.load()
    cache: dict = {}
    for y in range(out.size[1]):
        for x in range(out.size[0]):
            colour = px[x, y]
            if colour not in cache:
                cache[colour] = imageops._nearest(colour, palette)
            px[x, y] = cache[colour]
    return out


# ---------------------------------------------------------------------------
# 16枚を合成する
# ---------------------------------------------------------------------------

def corner_mask(bits: tuple, size: int, seed: int, jitter: float = 0.02) -> list:
    """4隅の値を双線形で補間し、0.5 で切って upper 領域を作る。

    これが Wang の角タイルの定義そのものである。隣接するセルは
    頂点を共有するので、この作り方なら**接続は構造的に保証される。**

    jitter は境界を乱す量。**縁石には 0 に近い値を使うこと。**
    直線境界の中線では補間値がちょうど 0.5 になるため、乱すと
    画素が交互に反転して**縁石がのこぎり歯になる**（実測）。
    自然物の境界（草と土など）では 0.05 程度が自然に見える。
    """
    nw, ne, sw, se = bits
    rng = random.Random(seed)
    mask = []
    for y in range(size):
        v = (y + 0.5) / size
        row = []
        for x in range(size):
            u = (x + 0.5) / size
            value = (nw * (1 - u) * (1 - v) + ne * u * (1 - v)
                     + sw * (1 - u) * v + se * u * v)
            value += rng.uniform(-1.0, 1.0) * jitter   # 境界を少しだけ乱す
            row.append(1 if value > 0.5 else 0)
        mask.append(row)
    return mask


def draw_curb(image: Image.Image, mask: list, top: tuple, base: tuple) -> None:
    """境界に縁石を描く。上側1px に天端、下側1px に接地影。

    **縁石は連続した構造物であり、点在する装飾ではない。**
    ゆえに ground_detail のデカールではなく、タイル側で描く。

    接地影を1px だけ焼くのは第5節の結論と整合する。
    長く伸びる落ち影は実行時に作る。ここで描くのは
    「そこに段差がある」という最小限の手がかりだけである。
    """
    size = image.size[0]
    px = image.load()
    top_edge, base_edge = [], []
    for y in range(size):
        for x in range(size):
            neighbours = [(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                          if 0 <= x + dx < size and 0 <= y + dy < size]
            if mask[y][x] and any(not mask[j][i] for i, j in neighbours):
                top_edge.append((x, y))
            elif not mask[y][x] and any(mask[j][i] for i, j in neighbours):
                base_edge.append((x, y))
    for x, y in top_edge:
        px[x, y] = top
    for x, y in base_edge:
        px[x, y] = base


def build_wang(lower: list, upper: list, palette: list, seed: int,
               curb: bool, curb_top: tuple, curb_base: tuple,
               jitter: float = 0.02) -> list:
    """2素材と角マスクから16枚を合成する。"""
    rng = random.Random(seed)
    tiles = []
    size = lower[0].size[0]
    for index in range(16):
        bits = ((index >> 3) & 1, (index >> 2) & 1, (index >> 1) & 1, index & 1)
        mask = corner_mask(bits, size, seed + index, jitter)
        lo = rng.choice(lower).convert("RGB")
        up = rng.choice(upper).convert("RGB")
        image = Image.new("RGB", (size, size))
        px, pl, pu = image.load(), lo.load(), up.load()
        for y in range(size):
            for x in range(size):
                px[x, y] = pu[x, y] if mask[y][x] else pl[x, y]
        if curb and 0 < sum(sum(row) for row in mask) < size * size:
            draw_curb(image, mask, curb_top, curb_base)
        tiles.append({
            "name": "wang_%d" % index,
            "corners": {k: ("upper" if b else "lower") for k, b in zip(CORNERS, bits)},
            "image": snap(image, palette),
        })
    return tiles


def layout(tiles: list, cols: int, rows: int, seed: int) -> Image.Image:
    """ランダム配置で広い面を作る。**反復への唯一有効な対策**（実測）。"""
    rng = random.Random(seed)
    size = tiles[0].size[0]
    canvas = Image.new("RGB", (cols * size, rows * size))
    for y in range(rows):
        for x in range(cols):
            canvas.paste(rng.choice(tiles), (x * size, y * size))
    return canvas


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_region(text: str) -> tuple:
    parts = text.split(",")
    if len(parts) != 4 or not all(p.strip().lstrip("-").isdigit() for p in parts):
        raise argparse.ArgumentTypeError("--region は x,y,w,h 形式で指定してください: " + text)
    return tuple(int(p) for p in parts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tile_from_texture.py",
        description="自作画像から 32px の Wang タイルセットを合成する（API を使わない）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config.add_project_arg(parser)
    parser.add_argument("--source", required=True, metavar="PATH",
                        help="素材画像。プロジェクト相対または絶対パス。")
    parser.add_argument("--region", action="append", required=True, type=parse_region,
                        metavar="X,Y,W,H", help="使う領域。複数指定できる（繋げて1枚の素材にする）。")
    parser.add_argument("--name", required=True, help="タイルセット名。")
    parser.add_argument("--out", required=True, metavar="PATH", help="出力先（プロジェクト相対）。")
    parser.add_argument("--palette", default="palettes/iwato_64_colors_terrain.png",
                        help="吸着先パレット（既定: 地の52色）。")
    parser.add_argument("--tile-src-px", type=int, default=64,
                        help="1タイルが覆う元画素数（既定: 64）。大きいほど広い範囲が1タイルに入る。")
    parser.add_argument("--contrast", type=float, default=0.5,
                        help="コントラスト圧縮率（既定: 0.5）。**1.0 は迷彩になる**。")
    parser.add_argument("--variants", type=int, default=12, help="切り出すバリエーション数（既定: 12）。")
    parser.add_argument("--upper-shift", type=int, default=30,
                        help="upper を作る明度差（既定: +30）。**別素材にはしない**（第10節）。")
    parser.add_argument("--stretch", default="auto",
                        help="縦の引き伸ばし率。auto なら斑の異方性から推定する。")
    parser.add_argument("--seed", type=int, default=0, help="乱数種（既定: 0）。同じ種なら同じ出力。")
    parser.add_argument("--heal-cracks", dest="heal", action="store_true", default=True,
                        help="細い暗線を消す（既定: 有効）。")
    parser.add_argument("--no-heal-cracks", dest="heal", action="store_false")
    parser.add_argument("--curb", dest="curb", action="store_true", default=True,
                        help="境界に縁石を描く（既定: 有効）。")
    parser.add_argument("--no-curb", dest="curb", action="store_false")
    parser.add_argument("--curb-top", default="#7F8A92", help="縁石の天端の色（既定: 中性の明るい灰）。")
    parser.add_argument("--curb-base", default="#171C24", help="接地影の色（既定: ink の暗部）。")
    parser.add_argument("--boundary-jitter", type=float, default=0.02,
                        help="地形境界の乱れ（既定: 0.02）。**縁石は 0 付近**。自然物は 0.05 程度。")
    parser.add_argument("--heal-radius", type=int, default=3,
                        help="ひび除去の半径（既定: 3）。上げすぎると斑まで消える。")
    return parser


def _hex(text: str) -> tuple:
    text = text.lstrip("#")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config.load_project(args.project)
    root = config.project_dir(args.project)

    source_path = Path(args.source)
    if not source_path.is_absolute():
        source_path = root / args.source
    if not source_path.is_file():
        raise SystemExit("素材画像が見つかりません: %s" % source_path)
    palette_path = root / args.palette if not Path(args.palette).is_absolute() else Path(args.palette)
    palette = load_palette(palette_path)

    image = Image.open(source_path).convert("RGB")
    print("素材      : %s  %dx%d" % (args.source, image.width, image.height))
    print("パレット  : %s  %d 色" % (args.palette, len(palette)))

    # 1. 遠近の補正 ---------------------------------------------------------
    crops = [image.crop((x, y, x + w, y + h)) for x, y, w, h in args.region]
    if args.stretch == "auto":
        estimates = [estimate_stretch(c) for c in crops]
        stretch = sum(estimates) / len(estimates)
        print("縦の圧縮  : 領域ごとに %s → 平均 %.2f 倍に伸ばす"
              % (" / ".join("%.2f" % e for e in estimates), stretch))
    else:
        stretch = float(args.stretch)
        print("縦の圧縮  : %.2f 倍（指定値）" % stretch)

    rectified = [c.resize((c.width, max(1, int(round(c.height * stretch)))), Image.LANCZOS)
                 for c in crops]
    width = sum(r.width for r in rectified)
    height = max(r.height for r in rectified)
    source = Image.new("RGB", (width, height))
    offset = 0
    for r in rectified:
        source.paste(r, (offset, 0))
        offset += r.width
    print("補正後    : %dx%d" % source.size)

    # 2. ひびの除去 ---------------------------------------------------------
    if args.heal:
        source, healed = heal_cracks(source, radius=args.heal_radius)
        print("ひび除去  : %d 画素（全体の %.1f%%）"
              % (healed, 100.0 * healed / (source.size[0] * source.size[1])))

    # 3〜5. 窓の選別・縮小・コントラスト・吸着 --------------------------------
    windows = pick_windows(source, args.tile_src_px, args.variants)
    if len(windows) < 2:
        raise SystemExit("窓が %d 枚しか取れませんでした。素材の面積が足りません。" % len(windows))
    small = match_means([w.resize((32, 32), Image.LANCZOS) for w in windows])
    lower = [snap(compress_contrast(t, args.contrast), palette) for t in small]
    upper = [snap(compress_contrast(t, args.contrast, args.upper_shift), palette) for t in small]
    print("バリエーション: %d 枚（1タイル = 元画素 %d）" % (len(lower), args.tile_src_px))
    print("lower     : ざらつき %.2f / 周期性 %.2f"
          % (sum(roughness(t) for t in lower) / len(lower),
             sum(periodicity(t) for t in lower) / len(lower)))
    print("upper     : ざらつき %.2f / 周期性 %.2f"
          % (sum(roughness(t) for t in upper) / len(upper),
             sum(periodicity(t) for t in upper) / len(upper)))

    # 6. 16枚の合成 ---------------------------------------------------------
    tiles = build_wang(lower, upper, palette, args.seed, args.curb,
                       _hex(args.curb_top), _hex(args.curb_base), args.boundary_jitter)

    out_dir = root / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"tileset": {"total_tiles": len(tiles), "tile_size": {"width": 32, "height": 32},
                           "terrain_types": ["lower", "upper"], "tiles": []}}
    for tile in tiles:
        buffer = io.BytesIO()
        tile["image"].save(buffer, "PNG")
        payload["tileset"]["tiles"].append({
            "id": tile["name"], "name": tile["name"], "corners": tile["corners"],
            "image": {"type": "base64",
                      "base64": base64.b64encode(buffer.getvalue()).decode(), "format": "png"},
        })
        tile["image"].save(out_dir / ("%s.png" % tile["name"]))
    (out_dir / "tileset.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    layout(lower, 20, 11, args.seed + 1).save(out_dir / "field_lower.png")
    layout(upper, 20, 11, args.seed + 1).save(out_dir / "field_upper.png")

    colours = {p for t in tiles for p in t["image"].get_flattened_data()}
    outside = [c for c in colours if c not in set(palette)]
    print("")
    print("使用色    : %d 色 / パレット外 %d 色" % (len(colours), len(outside)))
    print("出力      : %s" % out_dir.relative_to(config.ROOT))
    print("")
    print("次: python tools/assemble_tileset.py --project %s --input %s --mask road --scale 6"
          % (args.project, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
