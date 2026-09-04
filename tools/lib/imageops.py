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


def _nearest(colour: tuple, palette: list) -> tuple:
    """パレット中で最も近い色を返す（重み付きユークリッド距離）。"""
    r, g, b = colour
    best, best_d = palette[0], None
    for pr, pg, pb in palette:
        # 人間の感度に合わせた重み。緑を重く見る
        d = 2 * (r - pr) ** 2 + 4 * (g - pg) ** 2 + 3 * (b - pb) ** 2
        if best_d is None or d < best_d:
            best, best_d = (pr, pg, pb), d
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
