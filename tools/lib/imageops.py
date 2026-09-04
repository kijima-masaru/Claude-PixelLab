"""ドット絵の後処理・検査に使う画像操作。

postprocess.py / validate_assets.py / normalmap.py が共有する。
判定値（タイルサイズ・色数・パレット）は必ず project.yaml 由来のものを
引数で受け取り、この層には持たない。
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

#: 半透明とみなすアルファ値の範囲。ドット絵では 0 か 255 のみを許す。
ALPHA_OPAQUE = 255
ALPHA_TRANSPARENT = 0


def load_rgba(path: Path) -> Image.Image:
    """PNG を RGBA で読む。"""
    return Image.open(path).convert("RGBA")


# --- パレット ---------------------------------------------------------------

def load_palette(path: Path) -> list:
    """パレットファイルを読み、[(r, g, b), ...] を返す。

    対応形式は GIMP/Aseprite の .gpl と、1行1色の HEX テキスト（.hex）。
    """
    colours: list = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") and len(line) not in (7, 4):
            continue
        if line.lower().startswith(("gimp palette", "name:", "columns:")):
            continue
        if line.startswith("#"):
            hexpart = line[1:]
            if len(hexpart) == 3:
                hexpart = "".join(ch * 2 for ch in hexpart)
            if len(hexpart) == 6:
                try:
                    colours.append(tuple(int(hexpart[i:i + 2], 16) for i in (0, 2, 4)))
                except ValueError:
                    pass
            continue
        parts = line.split()
        if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
            colours.append(tuple(int(p) for p in parts[:3]))
    # 重複を保ちつつ順序を維持して除去
    seen, unique = set(), []
    for colour in colours:
        if colour not in seen:
            seen.add(colour)
            unique.append(colour)
    return unique


def _srgb_to_lab(colour: tuple) -> tuple:
    """sRGB を CIE Lab へ変換する（D65）。"""
    def linear(v: float) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in colour)
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x / 0.95047), f(y), f(z / 1.08883)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _nearest(colour: tuple, palette: list) -> tuple:
    """パレット中で最も近い色を返す（CIE Lab のユークリッド距離）。

    **重み付き RGB を使ってはならない。** 以前の実装は
    `2R²+4G²+3B²` だったが、これは**中性の灰色を紫ランプへ吸着させる**。

    実測（自作ゲームの舗装 32x32 を地の52色へ吸着し、吸着先の系統を数えた）:

        元画像            中性 78.6% / 藍  7.4% / 紫 14.0%
        重み付きRGB(旧)   中性 73.5% / 藍 20.3% / 紫  6.1%   ← 紫が残る
        CIE Lab           中性 78.7% / 藍 21.3% / 紫  0.0%   ← 元の分布に最も近い

    生成物は最初からパレット内に収まっており（PILOT_FINDINGS 第4節）、
    後処理が実質無変換だったため、この欠陥はこれまで表面化しなかった。
    **パレット外の画像を吸着させた瞬間に問題になる。** 詳細は第12節。
    """
    target = _srgb_to_lab(colour)
    best, best_d = palette[0], None
    for candidate in palette:
        lab = _srgb_to_lab(candidate)
        d = sum((lab[i] - target[i]) ** 2 for i in range(3))
        if best_d is None or d < best_d:
            best, best_d = candidate, d
    return best


def apply_palette(image: Image.Image, palette: list | None, max_colors: int) -> Image.Image:
    """パレットへ強制的に量子化する。ディザリングは行わない。

    palette が None のときは max_colors 色へ減色するのみ
    （パレット未確定の段階でもパイプラインを通すための経路）。
    """
    image = image.convert("RGBA")
    alpha = image.getchannel("A")

    if palette:
        cache: dict = {}
        rgb = image.convert("RGB")
        pixels = list(rgb.getdata())
        mapped = []
        for pixel in pixels:
            hit = cache.get(pixel)
            if hit is None:
                hit = _nearest(pixel, palette)
                cache[pixel] = hit
            mapped.append(hit)
        out = Image.new("RGB", image.size)
        out.putdata(mapped)
    else:
        # ディザリングなしのメディアンカット
        out = image.convert("RGB").quantize(
            colors=max_colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
        ).convert("RGB")

    out = out.convert("RGBA")
    out.putalpha(alpha)
    return out


def strip_colors(image: Image.Image, forbidden: list, allowed: list) -> tuple:
    """禁止した色を、許した色のうち最も近いものへ置き換える。

    **保険である。** 本筋は color_image に渡さないことで最初から
    出させないこと。ただし光源色が地形に混入すると
    「彩度の高い色は光源にのみ許される」という原則が壊れるため、
    後段でも落とせるようにしておく。
    """
    if not forbidden or not allowed:
        return image, 0
    forbidden_set = set(forbidden)
    image = image.convert("RGBA")
    out = image.copy()
    px = out.load()
    cache: dict = {}
    changed = 0
    for y in range(image.height):
        for x in range(image.width):
            r, g, b, a = px[x, y]
            if a == ALPHA_TRANSPARENT or (r, g, b) not in forbidden_set:
                continue
            hit = cache.get((r, g, b))
            if hit is None:
                hit = _nearest((r, g, b), allowed)
                cache[(r, g, b)] = hit
            px[x, y] = (hit[0], hit[1], hit[2], a)
            changed += 1
    return out, changed


def count_colors(image: Image.Image, ignore_transparent: bool = True) -> set:
    """使用されている RGB 色の集合を返す。完全透明画素は既定で無視する。"""
    image = image.convert("RGBA")
    used = set()
    for r, g, b, a in image.getdata():
        if ignore_transparent and a == ALPHA_TRANSPARENT:
            continue
        used.add((r, g, b))
    return used


# --- 透明度 -----------------------------------------------------------------

def binarize_alpha(image: Image.Image, threshold: int = 128) -> Image.Image:
    """アルファを 0 か 255 に二値化する。中間値を作らない。"""
    image = image.convert("RGBA")
    alpha = image.getchannel("A").point(
        lambda a: ALPHA_OPAQUE if a >= threshold else ALPHA_TRANSPARENT
    )
    out = image.copy()
    out.putalpha(alpha)
    return out


def semi_transparent_pixels(image: Image.Image) -> int:
    """半透明画素の数を返す。"""
    image = image.convert("RGBA")
    return sum(
        1 for _, _, _, a in image.getdata()
        if a not in (ALPHA_TRANSPARENT, ALPHA_OPAQUE)
    )


# --- アンチエイリアス --------------------------------------------------------

def remove_antialias(image: Image.Image, palette: list | None, max_colors: int) -> Image.Image:
    """輪郭に生じた中間色を除去する。

    実体は「アルファの二値化 + パレットへの吸着」である。
    パレット外の中間色はパレット適用で最近色へ吸われ、
    半透明の縁は二値化で消える。ドット絵ではこれで十分であり、
    ぼかしを伴う処理を入れないほうが結果が安定する。
    """
    image = binarize_alpha(image)
    return apply_palette(image, palette, max_colors)


# --- グリッド ---------------------------------------------------------------

def trim_transparent(image: Image.Image) -> Image.Image:
    """周囲の完全透明な余白を取り除く。"""
    image = image.convert("RGBA")
    bbox = image.getchannel("A").getbbox()
    return image.crop(bbox) if bbox else image


def align_to_grid(image: Image.Image, tile_size: int, mode: str = "pad") -> Image.Image:
    """寸法を tile_size の倍数に整える。

    mode="pad"  余白を透明で足して切り上げる（既定。情報を失わない）
    mode="crop" はみ出しを切り落として切り捨てる
    """
    image = image.convert("RGBA")
    w, h = image.size
    if mode == "crop":
        nw = max(tile_size, (w // tile_size) * tile_size)
        nh = max(tile_size, (h // tile_size) * tile_size)
        left = (w - nw) // 2
        top = (h - nh) // 2
        return image.crop((left, top, left + nw, top + nh))

    nw = int(math.ceil(w / tile_size)) * tile_size
    nh = int(math.ceil(h / tile_size)) * tile_size
    if (nw, nh) == (w, h):
        return image
    canvas = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
    canvas.paste(image, ((nw - w) // 2, (nh - h) // 2))
    return canvas


def is_grid_aligned(image: Image.Image, tile_size: int) -> bool:
    w, h = image.size
    return w % tile_size == 0 and h % tile_size == 0


# --- ノーマルマップ ----------------------------------------------------------

def generate_normalmap(image: Image.Image, strength: float = 1.0,
                       method: str = "sobel", flip_y: bool = True) -> Image.Image:
    """高さとみなした輝度からノーマルマップを生成する。

    flip_y=True で法線の Y 成分を反転する。**Godot ではこれが必要である。**
    Godot の 2D ライトは Y 軸を下向きに取るため、一般的な OpenGL 規約の
    ノーマルマップをそのまま渡すと、陰影が上下逆になる。

    ドット絵の輪郭を保つため、ぼかしを一切かけずに1画素差分で求める。
    """
    rgba = image.convert("RGBA")
    w, h = rgba.size
    alpha = list(rgba.getchannel("A").getdata())
    height = list(rgba.convert("L").getdata())

    out = Image.new("RGBA", (w, h), (128, 128, 255, 0))
    pixels = out.load()

    def sample(x: int, y: int) -> float:
        x = min(max(x, 0), w - 1)
        y = min(max(y, 0), h - 1)
        index = y * w + x
        if alpha[index] == ALPHA_TRANSPARENT:
            return 0.0
        return height[index] / 255.0

    for y in range(h):
        for x in range(w):
            if alpha[y * w + x] == ALPHA_TRANSPARENT:
                continue
            if method == "sobel":
                dx = (
                    (sample(x + 1, y - 1) + 2 * sample(x + 1, y) + sample(x + 1, y + 1))
                    - (sample(x - 1, y - 1) + 2 * sample(x - 1, y) + sample(x - 1, y + 1))
                ) / 4.0
                dy = (
                    (sample(x - 1, y + 1) + 2 * sample(x, y + 1) + sample(x + 1, y + 1))
                    - (sample(x - 1, y - 1) + 2 * sample(x, y - 1) + sample(x + 1, y - 1))
                ) / 4.0
            else:  # "height": 単純な前方差分
                dx = sample(x + 1, y) - sample(x, y)
                dy = sample(x, y + 1) - sample(x, y)

            nx = -dx * strength
            ny = -dy * strength
            if flip_y:
                ny = -ny
            nz = 1.0
            length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            pixels[x, y] = (
                int(round((nx / length * 0.5 + 0.5) * 255)),
                int(round((ny / length * 0.5 + 0.5) * 255)),
                int(round((nz / length * 0.5 + 0.5) * 255)),
                ALPHA_OPAQUE,
            )
    return out


# --- 保存 -------------------------------------------------------------------

def save_png(image: Image.Image, path: Path) -> None:
    """完成品として PNG を保存する。圧縮による色の変化はない（可逆）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGBA").save(path, format="PNG", optimize=True)
