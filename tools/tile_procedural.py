#!/usr/bin/env python3
"""ノイズから 32px の Wang タイルセットを合成する。**API も素材画像も使わない。**

    python tools/tile_procedural.py --project iwato --name tile_soil_grass \
        --lower warm --upper olive --out _work/tile_soil_grass

**トーラス上で生成するため、継ぎ目は原理的に生じない。**
256px の面から 8x8=64 枚を切り出せば、互いに完全に繋がったタイルが
64枚得られる。反復の周期は 32px ではなく 8タイル（8m）になる。

設計の要点は3つ。詳細は docs/PILOT_FINDINGS.md の第13・14節。

  1. **1つの素材は1つの色相で作る。** 階調は明度差だけで作る。
     色相を足して質感を補おうとすると**迷彩になる**（第14節）
  2. **質感が足りなければコントラストと斑の細かさを上げる。**
     色相ではない。目標は ざらつき 3.5〜6.0
  3. 反復の判定には `procgen.grid_visibility()` を使う。
     従来の周期性は 1枚のタイルの自己反復を測るもので、
     **この作り方には当てはまらない**
"""

from __future__ import annotations

import argparse
import base64
import math
import colorsys
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402
from lib import procgen  # noqa: E402
from tile_from_texture import (build_wang, load_palette, roughness,  # noqa: E402
                               snap)

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow が必要です: python -m pip install -r requirements.txt")


#: 系統名 → (色相の下限, 色相の上限, 彩度の上限)。地の色から系統を取り出す。
#: 系統名 → (色相の下限, 色相の上限, 彩度の上限, 彩度の下限)。
#:
#: **彩度の下限が要る。** 彩度が 0.05 を下回る色は、色相が事実上定まらない。
#: 下限を置かないと、ほぼ白の `#EFF0F0` が「緑」として拾われ、
#: ランプの平均段差が 31.7 まで開いて**ざらつきが目標帯を突き抜ける**（実測）。
#:
#: `concrete` だけは中性そのものが素材なので下限を置かない。ただし
#: **暖色の灰は除く**（青灰と暖灰を混ぜると色相の広がりが 175度 になる）。
FAMILIES = {
    "olive": (55, 95, 1.0, 0.08),
    "warm": (20, 50, 0.16, 0.06),
    "earth": (0, 45, 1.0, 0.18),
    # 緑ランプは暗端が色相198度（青緑）まで振れる。窓を 95-180 に
    # していたため**暗い緑が落ちて、鮮やかな明部しか残らなかった。**
    "green": (95, 200, 1.0, 0.16),
    "indigo": (195, 250, 1.0, 0.20),
    "concrete": (195, 250, 0.22, 0.0),
}


def _hls(colour):
    return colorsys.rgb_to_hls(*[v / 255 for v in colour])


def family(palette: list, name: str) -> list:
    """パレットから系統を明度順に取り出す。**混ぜない。1系統だけを使う。**"""
    if name not in FAMILIES:
        raise SystemExit("未知の系統: %s / 既知: %s" % (name, ", ".join(sorted(FAMILIES))))
    low, high, max_s, min_s = FAMILIES[name]
    picked = [c for c in palette
              if low <= _hls(c)[0] * 360 <= high
              and min_s <= _hls(c)[2] <= max_s]
    if not picked:
        raise SystemExit("系統 %s の色がパレットにありません" % name)
    return sorted(picked, key=lambda c: _hls(c)[1])


#: 主系統に必要な最小の段数。これを割ると段差が大きくなり、
#: ざらつきが目標帯を超える（warm 4段で 7.18、6段で 4.72。実測）。
MIN_RAMP_STEPS = 6


def sub_ramp(ramp: list, lo: float, hi: float) -> list:
    """ランプの一部だけを取り出す。0.0〜1.0 の割合で指定する。

    **同じ系統の2素材を組むときに要る。** 板張り×少し明るい板張り、
    トタン×少し明るいトタンなど。全域を両方に使うと同じ物になる。
    段数が6を割らないよう、足りなければ端を広げる。
    """
    n = len(ramp)
    start, end = int(lo * n), max(int(hi * n), int(lo * n) + 1)
    picked = ramp[start:end]
    while len(picked) < min(MIN_RAMP_STEPS, n):
        if end < n:
            end += 1
        elif start > 0:
            start -= 1
        else:
            break
        picked = ramp[start:end]
    return picked


def render_field(ramp: list, size: int, seed: int, contrast: float,
                 octaves: int, base_cells: int, bias: float,
                 gain: float = 1.0) -> Image.Image:
    """ノイズをランプへ写す。**ランプは1系統。色相は動かない。**"""
    field = procgen.fbm(size, octaves, seed=seed, base_cells=base_cells, gain=gain)
    image = Image.new("RGB", (size, size))
    px = image.load()
    steps = len(ramp)
    for y in range(size):
        for x in range(size):
            value = (field[y][x] - 0.5) * contrast + bias
            px[x, y] = ramp[max(0, min(steps - 1, int(value * steps)))]
    return image


def _pattern_mark(size: int, seed: int, pattern: str, pitch: int, cells: int):
    """模様そのものを作る。**ノイズやランプとは切り離してある。**

    畳・板張り・敷石・トタンは、反復が正しい素材である（第10節）。
    ただし**色相は1系統のまま**であり、模様は明度差だけで作る（第14節）。
    """
    if pattern == "grid":
        # **目地の位置を低周波ノイズで揺らす。** 揺らさないと、周期が
        # 32px を割り切って全タイルが同一になり「壁紙」と判定される
        # （実測: 格子の目立ちやすさ 0.58 → 0.07）。
        # トーラス上で継ぎ目が生じないよう、周期境界のノイズを使う。
        dx = procgen.value_noise(size, 4, seed + 83)
        dy = procgen.value_noise(size, 4, seed + 97)
        pitch_y = max(4, pitch // 2)
        mark = [[0] * size for _ in range(size)]
        for y in range(size):
            for x in range(size):
                sx = x + (dx[y][x] - 0.5) * pitch * 1.2
                sy = y + (dy[y][x] - 0.5) * pitch_y * 1.2
                row = int(sy // pitch_y)
                shift = (row * 0.5 * pitch) % pitch
                mark[y][x] = 1 if (int(sy) % pitch_y) < 1 or (int(sx + shift) % pitch) < 1 else 0
        return mark, 0.30
    if pattern == "waves":
        # ★ 波の本数を、**タイル数（size/32）の倍数から外す。**
        #
        # 周期が 32px を割り切ると、横に32pxずらしただけで縞が位相ごと
        # 重なり、全タイルが同一と判定される（実測: 格子 0.45）。
        # 揺らぎを強くしても解けなかった。揺らぎは滑らかで、32px の間では
        # ほとんど変化しないためである。
        #
        # 面の一辺 256px に対して波を整数本入れれば、トーラス上で継ぎ目は
        # 生じる余地がない。その本数を 8 の倍数から1つずらせば、
        # **32px ずらしたときに位相が 1/8 だけ回り、重ならなくなる。**
        # 32px ずらしたときの位相のずれは count / tiles_per_side 周期ぶんになる。
        # **その小数部が 0.5 のとき、自己相関が最小になる。**
        # 1本ずらす（小数部 0.125）では cos(0.125*2π)=0.71 で足りなかった。
        tiles_per_side = max(1, size // 32)
        target = tiles_per_side // 2
        count = max(1, round(size / pitch))
        while count % tiles_per_side != target:
            count += 1
        drift = procgen.value_noise(size, 4, seed + 71)
        return [[(math.sin((x / size * count + (drift[y][x] - 0.5) * 0.35) * 2 * math.pi) + 1) / 2
                 for x in range(size)] for y in range(size)], 0.36
    if pattern == "voronoi":
        _, edge = procgen.voronoi(size, cells, seed=seed + 3, jitter=0.7)
        return [[0 if edge[y][x] < 1.6 else 1 for x in range(size)] for y in range(size)], 0.30
    if pattern == "strokes":
        return procgen.strokes(size, size * size // 12, seed=seed + 5, length=3), 0.22
    return None, 0.0


def render_pattern(ramp: list, size: int, seed: int, pattern: str, contrast: float,
                   octaves: int, base_cells: int, bias: float, gain: float,
                   pitch: int, cells: int, depth_override=None) -> Image.Image:
    """模様と下地のノイズを重ね、ランプへ写す。

    どの模様も、下地に細かいノイズを敷いてから重ねる。
    ノイズが無いと単調な図形になり、素材に見えない。
    """
    base = procgen.fbm(size, octaves, seed=seed, base_cells=base_cells, gain=gain)
    mark, depth = _pattern_mark(size, seed, pattern, pitch, cells)
    if depth_override is not None:
        depth = depth_override
    return _map_to_ramp(base, mark, pattern, depth, ramp, size, contrast, bias)


def _map_to_ramp(base, mark, pattern, depth, ramp, size, contrast, bias):
    """ノイズと模様をランプへ写す。**ノイズの計算とは分けてある。**

    コントラストの自動調整で何度も呼ぶため。fbm の計算は重いが、
    写像は軽い。**同じノイズを使い回せば探索が実質ただになる。**
    """
    image = Image.new("RGB", (size, size))
    px = image.load()
    steps = len(ramp)
    for y in range(size):
        for x in range(size):
            value = (base[y][x] - 0.5) * contrast + bias
            if mark is not None:
                m = mark[y][x]
                # **目地は暗い。** 明るく描くと「線」として主張しすぎる。
                value += ((m - 0.5) * 2 * depth if pattern == "waves"
                          else (-depth if m else depth * 0.15))
            px[x, y] = ramp[max(0, min(steps - 1, int(value * steps)))]
    return image


def auto_contrast(ramp, size, seed, pattern, octaves, base_cells, bias, gain,
                  pitch, cells, depth_override, palette, low=3.5, high=6.0):
    """ざらつきが目標帯に入るコントラストを探す。**ノイズは1回しか作らない。**

    ざらつきはコントラストだけでは決まらず、**ランプの段差**にも支配される。
    段差の大きいランプ（6段しかない系統）では、コントラストを下げても
    隣接2段を行き来するだけで下がらないことがある。その場合は
    最も近い値を返し、呼び出し側が不合格として扱う。
    """
    base = procgen.fbm(size, octaves, seed=seed, base_cells=base_cells, gain=gain)
    mark, depth = _pattern_mark(size, seed, pattern, pitch, cells)
    if depth_override is not None:
        depth = depth_override
    best = (None, None, 1e9)
    for step in range(30):
        contrast = 0.10 + step * 0.10
        image = snap(_map_to_ramp(base, mark, pattern, depth, ramp, size, contrast, bias), palette)
        value = sum(roughness(t) for t in slice_tiles(image)) / (size // 32) ** 2
        if low <= value <= high:
            return contrast, image, value
        distance = min(abs(value - low), abs(value - high))
        if distance < best[2]:
            best = (contrast, image, distance)
    contrast, image, _ = best
    value = sum(roughness(t) for t in slice_tiles(image)) / (size // 32) ** 2
    return contrast, image, value


def slice_tiles(image: Image.Image, tile: int = 32) -> list:
    size = image.size[0]
    return [image.crop((x, y, x + tile, y + tile))
            for y in range(0, size, tile) for x in range(0, size, tile)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tile_procedural.py",
        description="ノイズから 32px の Wang タイルセットを合成する（API を使わない）。")
    config.add_project_arg(parser)
    parser.add_argument("--name", required=True, help="タイルセット名。")
    parser.add_argument("--out", required=True, metavar="PATH", help="出力先（プロジェクト相対）。")
    parser.add_argument("--lower", required=True, choices=sorted(FAMILIES),
                        help="下の地形の系統。**1系統だけ**。")
    parser.add_argument("--upper", required=True, choices=sorted(FAMILIES),
                        help="上の地形の系統。**1系統だけ**。")
    parser.add_argument("--palette", default="palettes/iwato_colors_terrain.png")
    parser.add_argument("--size", type=int, default=256,
                        help="生成する面の一辺（既定: 256 = 8x8タイル）。")
    parser.add_argument("--contrast", type=float, default=0.75,
                        help="ランプのどこまで使うか（既定: 0.75）。ざらつきの量を決める。")
    parser.add_argument("--contrast-lower", type=float, default=None,
                        help="下の地形だけコントラストを変える。**段数の少ないランプでは要る**"
                             "（4段のランプに同じ値を使うと段差が大きくなり、ざらつきが上振れする）。")
    parser.add_argument("--contrast-upper", type=float, default=None,
                        help="上の地形だけコントラストを変える。")
    parser.add_argument("--lower-range", default="0,1", metavar="LO,HI",
                        help="下の地形が使うランプの範囲（割合）。同系統の2素材を組むときに使う。")
    parser.add_argument("--upper-range", default="0,1", metavar="LO,HI")
    parser.add_argument("--lower-pattern", default="noise",
                        choices=["noise", "grid", "waves", "voronoi", "strokes"],
                        help="下の地形の模様。**規則的な素材では規則性が素材そのものである**。")
    parser.add_argument("--upper-pattern", default="noise",
                        choices=["noise", "grid", "waves", "voronoi", "strokes"])
    parser.add_argument("--pitch", type=int, default=16,
                        help="格子・波の周期（既定: 16）。**32を割り切る値にすること**。")
    parser.add_argument("--cells", type=int, default=64, help="ボロノイの区画数（既定: 64）。")
    parser.add_argument("--lower-depth", type=float, default=None,
                        help="下の地形の模様の強さ。**強すぎるとざらつきが上振れする**。")
    parser.add_argument("--upper-depth", type=float, default=None, help="上の地形の模様の強さ。")
    parser.add_argument("--lower-bias", type=float, default=None,
                        help="下の地形の明るさ。**ランプのどのあたりを使うかを決める。** "
                             "彩度の高い明部を避けたいときは下げる（緑・木部）。")
    parser.add_argument("--upper-bias", type=float, default=None, help="上の地形の明るさ。")
    parser.add_argument("--auto-contrast", action="store_true", default=True,
                        help="ざらつきが目標帯（3.5〜6.0）に入るコントラストを自動で探す（既定: 有効）。")
    parser.add_argument("--no-auto-contrast", dest="auto_contrast", action="store_false")
    parser.add_argument("--gain", type=float, default=1.0,
                        help="オクターブの重み（既定: 1.0）。**斑の大きさを決める最重要の値**。"
                             "1未満だと粗い斑が支配して迷彩になる（標準的な fBm の既定 0.5 は地面に向かない）。")
    parser.add_argument("--octaves", type=int, default=5, help="ノイズの段数（既定: 5）。")
    parser.add_argument("--base-cells", type=int, default=24,
                        help="最も粗い斑の格子数（既定: 24）。斑の大きさを決める。")
    parser.add_argument("--bias", type=float, default=0.5, help="全体の明るさ（既定: 0.5）。")
    parser.add_argument("--seed", type=int, default=0, help="乱数種（既定: 0）。")
    parser.add_argument("--boundary-jitter", type=float, default=0.05,
                        help="地形境界の乱れ（既定: 0.05）。自然物は乱す。縁石は 0。")
    parser.add_argument("--edge", action="store_true",
                        help="境界に見切り線を引く（縁石・敷居用。自然物では使わない）。")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config.load_project(args.project)
    root = config.project_dir(args.project)
    palette = load_palette(root / args.palette)

    def rng_of(text):
        lo, hi = (float(v) for v in text.split(","))
        return lo, hi
    lower_ramp = sub_ramp(family(palette, args.lower), *rng_of(args.lower_range))
    upper_ramp = sub_ramp(family(palette, args.upper), *rng_of(args.upper_range))
    print("パレット  : %s（%d色）" % (args.palette, len(palette)))
    print("lower     : %s %d段  %s" % (args.lower, len(lower_ramp),
                                       " ".join("#%02X%02X%02X" % c for c in lower_ramp)))
    print("upper     : %s %d段  %s" % (args.upper, len(upper_ramp),
                                       " ".join("#%02X%02X%02X" % c for c in upper_ramp)))

    ct_lower = args.contrast_lower if args.contrast_lower is not None else args.contrast
    ct_upper = args.contrast_upper if args.contrast_upper is not None else args.contrast
    bias_lower = args.lower_bias if args.lower_bias is not None else args.bias
    bias_upper = args.upper_bias if args.upper_bias is not None else args.bias
    if args.auto_contrast:
        ct_lower, lower_field, rl = auto_contrast(
            lower_ramp, args.size, args.seed + 11, args.lower_pattern, args.octaves,
            args.base_cells, bias_lower, args.gain, args.pitch, args.cells,
            args.lower_depth, palette)
        ct_upper, upper_field, ru = auto_contrast(
            upper_ramp, args.size, args.seed + 23, args.upper_pattern, args.octaves,
            args.base_cells, bias_upper, args.gain, args.pitch, args.cells,
            args.upper_depth, palette)
        print("コントラスト自動: lower %.2f（ざらつき%.2f） / upper %.2f（ざらつき%.2f）"
              % (ct_lower, rl, ct_upper, ru))
    else:
        lower_field = snap(render_pattern(lower_ramp, args.size, args.seed + 11, args.lower_pattern,
                                          ct_lower, args.octaves, args.base_cells, bias_lower,
                                          args.gain, args.pitch, args.cells, args.lower_depth), palette)
        upper_field = snap(render_pattern(upper_ramp, args.size, args.seed + 23, args.upper_pattern,
                                          ct_upper, args.octaves, args.base_cells, bias_upper,
                                          args.gain, args.pitch, args.cells, args.upper_depth), palette)
    lower_tiles = slice_tiles(lower_field)
    upper_tiles = slice_tiles(upper_field)

    per_side = args.size // 32
    print("面        : %dx%d → %dx%d = %d枚（反復の周期は %dタイル）"
          % (args.size, args.size, per_side, per_side, len(lower_tiles), per_side))
    print("lower     : ざらつき %.2f  / upper : ざらつき %.2f"
          % (sum(roughness(t) for t in lower_tiles) / len(lower_tiles),
             sum(roughness(t) for t in upper_tiles) / len(upper_tiles)))
    print("斑の大きさ（帯域比）: lower %.2f / upper %.2f （**1を超えると迷彩に見える。路面は0.31**）"
          % (procgen.grain_ratio(lower_field), procgen.grain_ratio(upper_field)))
    print("格子の目立ちやすさ: lower %.3f / upper %.3f （0.35未満なら格子は見えない）"
          % (procgen.grid_visibility(_tiled(lower_field), period=per_side),
             procgen.grid_visibility(_tiled(upper_field), period=per_side)))

    tiles = build_wang(lower_tiles, upper_tiles, palette, args.seed, args.edge,
                       (0, 0, 0), (0, 0, 0), args.boundary_jitter)

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
                      "base64": base64.b64encode(buffer.getvalue()).decode(), "format": "png"}})
        tile["image"].save(out_dir / ("%s.png" % tile["name"]))
    # ★ スーパータイル。**「代替タイル」ではない。**
    #   これは連続した1枚の面を切り分けたものであり、**元の並び順で
    #   置かなければならない。** ランダムに置くと連続性が壊れ、
    #   32px の格子が見える（実測: 格子の目立ちやすさ 0.08 → 0.36）。
    #   Godot 側では nx x ny のブロックとして、(x % nx, y % ny) で引くこと。
    payload["tileset"]["supertile"] = {"width": per_side, "height": per_side,
                                       "order": "row-major", "lower": [], "upper": []}
    for kind, variants in (("lower", lower_tiles), ("upper", upper_tiles)):
        for i, image in enumerate(variants):
            name = "super_%s_%02d" % (kind, i)
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, "PNG")
            payload["tileset"]["supertile"][kind].append({
                "id": name, "name": name, "row": i // per_side, "col": i % per_side,
                "image": {"type": "base64",
                          "base64": base64.b64encode(buffer.getvalue()).decode(), "format": "png"}})
            image.convert("RGB").save(out_dir / ("%s.png" % name))
    print("スーパータイル: %dx%d = %d枚ずつ（**元の並び順で置くこと**）"
          % (per_side, per_side, len(lower_tiles)))

    (out_dir / "tileset.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    lower_field.save(out_dir / "field_lower.png")
    upper_field.save(out_dir / "field_upper.png")

    colours = {p for t in tiles for p in t["image"].get_flattened_data()}
    outside = [c for c in colours if c not in set(palette)]
    print("")
    print("使用色    : %d 色 / パレット外 %d 色" % (len(colours), len(outside)))
    print("出力      : %s" % out_dir.relative_to(config.ROOT))
    return 0


def _tiled(field: Image.Image, cols: int = 2, rows: int = 2) -> Image.Image:
    canvas = Image.new("RGB", (field.width * cols, field.height * rows))
    for y in range(rows):
        for x in range(cols):
            canvas.paste(field, (x * field.width, y * field.height))
    return canvas


if __name__ == "__main__":
    sys.exit(main())
