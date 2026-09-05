#!/usr/bin/env python3
"""地面の装飾（ground_detail）を手続き的に作る。**API を使わない。**

    python tools/make_deco.py --project iwato --out _work/deco

タイルセットから外した「特徴」がここへ来る（PILOT_FINDINGS 第10節）。
白線・マンホール・グレーチング・側溝の蓋・礎石・用水路。
**どれも幾何で書ける。** 手続き的生成が最も正確な領域である。

タイルセットとの違いが2つある。

  - **透過を持つ。** アルファは 0 と 255 のみ（第5節の運用）
  - **接地影は 1〜2px だけ。** 長い落ち影は実行時に作る（第5節）

色はパレットから系統で取る。**1つの装飾に1系統**（第14節）。
"""

from __future__ import annotations

import argparse
import colorsys
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402
from lib import procgen  # noqa: E402
from tile_from_texture import load_palette  # noqa: E402

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow が必要です: python -m pip install -r requirements.txt")


TRANSPARENT = (0, 0, 0, 0)


def _hls(colour):
    return colorsys.rgb_to_hls(*[v / 255 for v in colour])


def ramp(palette: list, low: float, high: float, max_s: float, min_s: float = 0.0) -> list:
    """色相と彩度で系統を切り出し、明度順に返す。"""
    picked = [c for c in palette
              if low <= _hls(c)[0] * 360 <= high and min_s <= _hls(c)[2] <= max_s]
    return sorted(picked, key=lambda c: _hls(c)[1])


def canvas(w: int, h: int) -> Image.Image:
    return Image.new("RGBA", (w, h), TRANSPARENT)


def wear(image: Image.Image, ramp_colours: list, seed: int, amount: float = 0.22) -> None:
    """摩耗を散らす。**新品に見えると「生活の残り香」にならない。**

    不透明な画素の一部を、同じ系統の1段暗い色へ落とす。
    透明にはしない（穴が開くと 1px 収縮の検査に落ちる）。
    """
    rng = random.Random(seed)
    px = image.load()
    index = {c: i for i, c in enumerate(ramp_colours)}
    for y in range(image.height):
        for x in range(image.width):
            r, g, b, a = px[x, y]
            if a == 0 or rng.random() > amount:
                continue
            i = index.get((r, g, b))
            if i is not None and i > 0:
                px[x, y] = ramp_colours[i - 1] + (255,)


def contact_shadow(image: Image.Image, colour) -> None:
    """接地影を1pxだけ描く。**長い落ち影は実行時に作る**（第5節）。"""
    px = image.load()
    for x in range(image.width):
        for y in range(image.height - 1, 0, -1):
            if px[x, y][3] > 0:
                break
        else:
            continue
        if y + 1 < image.height and px[x, y + 1][3] == 0:
            px[x, y + 1] = colour + (255,)


# ---------------------------------------------------------------------------
# 個々の装飾
# ---------------------------------------------------------------------------

def painted_line(w, h, thickness, pale, seed, vertical=True):
    """路面標示・駐車枠・体育館のライン。**塗料は剥げる。**"""
    img = canvas(w, h)
    px = img.load()
    start = (w - thickness) // 2 if vertical else (h - thickness) // 2
    for y in range(h):
        for x in range(w):
            inside = (start <= x < start + thickness) if vertical else (start <= y < start + thickness)
            if inside:
                px[x, y] = pale[-1] + (255,)
    wear(img, pale, seed, 0.30)
    return img


def crosswalk(w, h, pale, seed):
    """横断歩道の1本。**縞ではなく1本の帯として作る。** 並べるのはマップ側。"""
    img = canvas(w, h)
    px = img.load()
    for y in range(2, h - 2):
        for x in range(w):
            px[x, y] = pale[-1] + (255,)
    wear(img, pale, seed, 0.26)
    return img


def manhole(size, metal, seed):
    """マンホールの蓋。同心円と放射の格子。**日本の路面の記号である。**"""
    img = canvas(size, size)
    px = img.load()
    cx = cy = (size - 1) / 2
    radius = size / 2 - 1
    rng = random.Random(seed)
    for y in range(size):
        for x in range(size):
            dx, dy = x - cx, y - cy
            d = math.hypot(dx, dy)
            if d > radius:
                continue
            angle = math.atan2(dy, dx)
            ring = int(d / 2.2)
            spoke = int((angle + math.pi) / (math.pi / 8))
            tone = 2 + ((ring + spoke) % 2)
            if d > radius - 1.6:
                tone = 1                      # 外周のリム
            px[x, y] = metal[min(tone, len(metal) - 1)] + (255,)
    wear(img, metal, seed + 1, 0.18)
    return img


def grating(w, h, metal, seed):
    """グレーチング。**溝の蓋は縦の桟が並ぶ。**"""
    img = canvas(w, h)
    px = img.load()
    for y in range(h):
        for x in range(w):
            bar = (x % 4) < 3
            px[x, y] = (metal[3] if bar else metal[0]) + (255,)
    for x in range(w):                        # 枠
        px[x, 0] = px[x, h - 1] = metal[1] + (255,)
    for y in range(h):
        px[0, y] = px[w - 1, y] = metal[1] + (255,)
    wear(img, metal, seed, 0.16)
    return img


def ditch_cover(w, h, stone, seed):
    """側溝の蓋。コンクリートの板に細い溝が2本。"""
    img = canvas(w, h)
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = stone[3] + (255,)
    for x in range(w):
        for y in (h // 3, h * 2 // 3):
            px[x, y] = stone[1] + (255,)
    for y in range(h):
        px[0, y] = px[w - 1, y] = stone[1] + (255,)
    wear(img, stone, seed, 0.24)
    return img


def foundation_stone(size, stone, seed):
    """礎石。**不定形の石をボロノイの1区画として切り出す。**"""
    img = canvas(size, size)
    px = img.load()
    cell, edge = procgen.voronoi(size, 6, seed=seed, jitter=0.8)
    target = cell[size // 2][size // 2]
    noise = procgen.fbm(size, 3, seed=seed + 5, base_cells=8, gain=1.0)
    for y in range(size):
        for x in range(size):
            if cell[y][x] != target:
                continue
            tone = 2 + int(noise[y][x] * 2.5)
            if edge[y][x] < 2.0:
                tone = 1                       # 石の縁は暗い
            px[x, y] = stone[min(tone, len(stone) - 1)] + (255,)
    return img


def irrigation_channel(w, h, stone, seed):
    """用水路。**地面に彫られた溝であり、水は実行時のライトで見せる。**"""
    img = canvas(w, h)
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = stone[3] + (255,)
    inner = w // 4
    for y in range(h):
        for x in range(inner, w - inner):
            px[x, y] = stone[0] + (255,)
    for y in range(h):
        px[inner - 1, y] = px[w - inner, y] = stone[1] + (255,)
    wear(img, stone, seed, 0.20)
    return img


def grass_edge(w, h, green, seed):
    """草の生え際。**歩道と草地の境に置く。** 上半分だけに草が立つ。"""
    img = canvas(w, h)
    px = img.load()
    rng = random.Random(seed)
    for x in range(w):
        height = rng.randint(h // 3, h - 2)
        thickness = rng.choice((1, 2, 2, 3))
        tone = green[rng.randrange(len(green))]
        for t in range(thickness):
            if x + t >= w:
                break
            for y in range(h - height, h):
                px[x + t, y] = tone + (255,)
    return img


def signboard_text(w, h, ink, seed, vertical=False):
    """**読めないが、文字の配置に見える模様。**

    32px = 1m では、幅2mの看板は 64px しかない。漢字は 12〜16px になり
    まず読めない（docs/NEXT_STEPS.md）。**読ませることは諦め、
    「文字が並んでいる」ことだけを示す。**

    文字の内容は近接時に UI で出す。素材側は模様でよい。
    横書き・縦書きの両方を作る。
    """
    img = canvas(w, h)
    px = img.load()
    rng = random.Random(seed)
    box = min(w, h) - 4 if not vertical else min(w, h) - 4
    step = box + 2
    positions = range(2, (h if vertical else w) - box, step)
    for start in positions:
        # 1文字ぶんの枠の中に、画のような短い線を数本置く
        strokes = rng.randint(3, 6)
        for _ in range(strokes):
            horizontal = rng.random() < 0.6
            if vertical:
                ox, oy = 2, start
            else:
                ox, oy = start, 2
            if horizontal:
                y = oy + rng.randrange(box)
                x0 = ox + rng.randrange(max(1, box // 3))
                for x in range(x0, min(ox + box, x0 + rng.randint(box // 2, box))):
                    if 0 <= x < w and 0 <= y < h:
                        px[x, y] = ink[-1] + (255,)
            else:
                x = ox + rng.randrange(box)
                y0 = oy + rng.randrange(max(1, box // 3))
                for y in range(y0, min(oy + box, y0 + rng.randint(box // 2, box))):
                    if 0 <= x < w and 0 <= y < h:
                        px[x, y] = ink[-1] + (255,)
    return img


# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="make_deco.py",
        description="地面の装飾（ground_detail）を手続き的に作る。")
    config.add_project_arg(parser)
    parser.add_argument("--out", required=True, metavar="PATH", help="出力先（プロジェクト相対）。")
    parser.add_argument("--palette", default="palettes/iwato_colors_terrain.png")
    parser.add_argument("--seed", type=int, default=0)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config.load_project(args.project)
    root = config.project_dir(args.project)
    palette = load_palette(root / args.palette)

    pale = ramp(palette, 195, 250, 0.13)[-5:]          # 白線用。ほぼ中性の明部
    metal = ramp(palette, 195, 250, 0.22)              # 鉄・コンクリート
    stone = ramp(palette, 195, 250, 0.22)
    green = ramp(palette, 55, 95, 1.0, 0.08)           # 草＝オリーブ（第15節）
    ink = ramp(palette, 195, 250, 0.13)

    items = {
        "deco_line_parking": painted_line(32, 64, 4, pale, args.seed + 1),
        "deco_line_gym": painted_line(32, 32, 3, pale, args.seed + 2),
        "deco_road_marking": crosswalk(32, 32, pale, args.seed + 3),
        "deco_manhole": manhole(32, metal, args.seed + 4),
        "deco_grating": grating(32, 32, metal, args.seed + 5),
        "obj_side_ditch_cover": ditch_cover(32, 32, stone, args.seed + 6),
        "obj_foundation_stone": foundation_stone(32, stone, args.seed + 7),
        "obj_irrigation_channel": irrigation_channel(32, 32, stone, args.seed + 8),
        "deco_grass_edge": grass_edge(32, 32, green, args.seed + 9),
        "deco_signboard_text_h": signboard_text(64, 32, ink, args.seed + 10),
        "deco_signboard_text_v": signboard_text(32, 64, ink, args.seed + 11, vertical=True),
    }
    out = root / args.out
    out.mkdir(parents=True, exist_ok=True)
    for name, image in items.items():
        if name in ("obj_foundation_stone",):
            contact_shadow(image, ink[0])
        image.save(out / ("%s.png" % name))
        print("  %-26s %dx%d" % (name, image.width, image.height))
    print("")
    print("%d 点を書き出しました: %s" % (len(items), out.relative_to(config.ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
