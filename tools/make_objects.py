#!/usr/bin/env python3
"""単体の物を手続き的に作れるかの試作。**API を使わない。**

    python tools/make_objects.py --project iwato --out _work/objects

タイルセットは全て「面を埋める素材」だったので手続き的生成が完勝した。
**オブジェクトは半分が形を持つ。** 境界は「幾何で書けるか」である。

  幾何で書ける      自販機・室外機・ポスト・ベンチ（直方体と面の分割）
  幾何で書けない    電柱・標識・鳥居・墓石（識別可能な形）

ここで試すのは前者。**2〜3回試して形にならなければ手描きへ回す。**
PixelLab に7回粘った経験を繰り返さない。

真上見下ろしであることに注意する。**見えるのは天板が主で、
手前（下）の面が少しだけ見える。** 側面は見えない（第1節）。
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


def _hls(colour):
    return colorsys.rgb_to_hls(*[v / 255 for v in colour])


def family(palette, low, high, max_s, min_s=0.0):
    return sorted([c for c in palette
                   if low <= _hls(c)[0] * 360 <= high and min_s <= _hls(c)[2] <= max_s],
                  key=lambda c: _hls(c)[1])


def box(w, h, ramp, seed, top=6, edge=3, inset=2, grime=0.40):
    """真上から見た直方体。**天板と、その縁だけ。**

    側面は見えない。縁を1段暗くして厚みを示し、天板に汚れを散らす。
    """
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    noise = procgen.fbm(max(w, h), 3, seed=seed, base_cells=10, gain=1.0)
    for y in range(inset, h - inset - 1):
        for x in range(inset, w - inset):
            tone = top if noise[y][x] > grime else top - 1
            px[x, y] = ramp[min(tone, len(ramp) - 1)] + (255,)
    for x in range(inset, w - inset):
        px[x, inset] = ramp[edge] + (255,)
        px[x, h - inset - 2] = ramp[edge] + (255,)
    for y in range(inset, h - inset - 1):
        px[inset, y] = ramp[edge] + (255,)
        px[w - inset - 1, y] = ramp[edge] + (255,)
    for x in range(inset, w - inset):          # 接地影 1px（第5節）
        px[x, h - inset - 1] = ramp[0] + (255,)
    return img


def vending_machine(metal, glow, seed):
    """自販機。**商品見本は上半分、取り出し口は下。**

    最初の試作は光る帯を下端に置いたため、上下が逆に見えた。
    真上から見た自販機は、天板の手前側に商品見本の窓が覗く。
    **光は窓の中だけ。周囲へは漏らさない**（実行時のライトが作る。第5節）。
    """
    w, h = 32, 64
    # 光る窓は明るい（明度138〜204）。筐体まで明るいと平均明度が
    # 地面の帯に入り、置いたときに沈む。**筐体は暗く保つ。**
    img = box(w, h, metal, seed, top=4, edge=2)
    px = img.load()
    # **窓は小さく。** 最初は 16行あり、光源色が面積の19%を占めて
    # 基準（15%以下）に落ちた。光る部分は物の一部である。
    win_top, win_bottom = 19, 31               # 上半分に窓
    for y in range(win_top, win_bottom):
        for x in range(8, w - 8):
            px[x, y] = glow[0] + (255,)
    for x in range(9, w - 9, 4):               # 缶の列
        for y in range(win_top + 2, win_bottom - 2):
            for k in range(2):
                if x + k < w - 8:
                    px[x + k, y] = glow[2] + (255,)
    for y in range(win_top, win_bottom):       # 窓枠
        px[7, y] = px[w - 8, y] = metal[2] + (255,)
    for y in range(h - 22, h - 14):            # 取り出し口（暗い凹み）
        for x in range(8, w - 8):
            px[x, y] = metal[1] + (255,)
    return img


def ac_unit(metal, seed):
    """室外機。**天板の格子と、手前のファンの円。**"""
    w, h = 32, 32
    img = box(w, h, metal, seed, top=6, edge=3)
    px = img.load()
    for y in range(6, h - 6, 3):               # 天板のフィン
        for x in range(5, w - 5):
            px[x, y] = metal[4] + (255,)
    cx, cy, r = w / 2, h * 0.62, 7
    for y in range(h):
        for x in range(w):
            d = math.hypot(x - cx, y - cy)
            if d < r:
                angle = math.atan2(y - cy, x - cx)
                blade = int((angle + math.pi) / (math.pi / 3)) % 2
                px[x, y] = metal[3 if blade else 2] + (255,)
            elif d < r + 1.2:
                px[x, y] = metal[1] + (255,)
    return img


def post_box(red, metal, seed):
    """郵便ポスト。**上から見れば丸い天板と、投函口の細い矩形。**"""
    w = h = 32
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    cx = cy = (w - 1) / 2
    noise = procgen.fbm(w, 3, seed=seed, base_cells=10, gain=1.0)
    for y in range(h):
        for x in range(w):
            d = math.hypot(x - cx, y - cy)
            if d > 11:
                continue
            tone = 3 if noise[y][x] > 0.45 else 2
            if d > 9.6:
                tone = 1
            px[x, y] = red[min(tone, len(red) - 1)] + (255,)
    for y in range(13, 16):                    # 投函口
        for x in range(10, w - 10):
            px[x, y] = metal[0] + (255,)
    for x in range(w):                         # 接地影
        for y in range(h - 1, 0, -1):
            if px[x, y][3] > 0:
                if y + 1 < h:
                    px[x, y + 1] = metal[0] + (255,)
                break
    return img


def bench(wood, metal, seed):
    """ベンチ。**上から見れば板が3枚並び、脚は見えない。**"""
    w, h = 64, 32
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    noise = procgen.fbm(w, 3, seed=seed, base_cells=14, gain=1.0)
    top, bottom = 8, 24
    for y in range(top, bottom):
        for x in range(2, w - 2):
            slat = (y - top) // 6
            tone = 4 - (slat % 2)
            if noise[y][x] < 0.42:
                tone -= 1
            px[x, y] = wood[max(0, min(tone, len(wood) - 1))] + (255,)
    for y in range(top, bottom, 6):            # 板の隙間
        for x in range(2, w - 2):
            px[x, y] = metal[0] + (255,)
    for x in range(2, w - 2):
        px[x, bottom] = metal[0] + (255,)      # 接地影
    return img


def tree(green, wood, seed):
    """樹木。**上から見た樹冠。輪郭が丸い塊で、中心に幹の暗い点。**

    L-system で枝を描くより、**塊としての樹冠**を作るほうが 32px には合う。
    ボロノイで葉の房を分け、房ごとに明度を変える。
    """
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    cx = cy = (size - 1) / 2
    cell, edge = procgen.voronoi(size, 24, seed=seed, jitter=0.9)
    noise = procgen.fbm(size, 3, seed=seed + 11, base_cells=6, gain=1.0)
    rng = random.Random(seed)
    tone_of = {i: rng.randrange(1, len(green)) for i in set(v for row in cell for v in row)}
    for y in range(size):
        for x in range(size):
            d = math.hypot(x - cx, y - cy)
            limit = size * 0.44 * (0.80 + 0.34 * noise[y][x])   # 輪郭を乱す
            if d > limit:
                continue
            tone = tone_of[cell[y][x]]
            if edge[y][x] < 1.4:
                tone = max(0, tone - 1)                          # 房の境目は暗い
            if d > limit - 2:
                tone = max(0, tone - 1)                          # 樹冠の外周
            px[x, y] = green[min(tone, len(green) - 1)] + (255,)
    for y in range(int(cy) - 2, int(cy) + 3):                    # 幹
        for x in range(int(cx) - 2, int(cx) + 3):
            px[x, y] = wood[1] + (255,)
    return img


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="make_objects.py",
        description="単体の物を手続き的に作れるかの試作。")
    config.add_project_arg(parser)
    parser.add_argument("--out", required=True, metavar="PATH")
    parser.add_argument("--palette", default="palettes/iwato_colors.png")
    parser.add_argument("--terrain-palette", default="palettes/iwato_colors_terrain.png")
    parser.add_argument("--seed", type=int, default=0)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config.load_project(args.project)
    root = config.project_dir(args.project)
    palette = load_palette(root / args.palette)
    terrain = set(load_palette(root / args.terrain_palette))
    lights = [c for c in palette if c not in terrain]

    metal = family(terrain, 195, 250, 0.22)
    # **暗い側だけを使う。** 明るいままだと平均明度が地面の帯
    # （26〜85）に入り、置いたときに沈む。
    wood = family(terrain, 20, 50, 0.16)[:3]
    green = family(terrain, 55, 95, 1.0, 0.08)[:3]
    red = family(terrain, 0, 45, 1.0, 0.18)
    glow = sorted([c for c in lights if 150 <= _hls(c)[0] * 360 <= 200],
                  key=lambda c: _hls(c)[1])

    items = {
        # **筐体は暗い側だけを使う。** 明るいままだと平均明度 82 となり、
        # 地面の帯（26〜85）に入って置いたときに沈む。
        "obj_vending_machine": vending_machine(metal[:9], glow, args.seed + 1),
        "obj_ac_unit": ac_unit(metal, args.seed + 2),
        "obj_post_box": post_box(red, metal, args.seed + 3),
        "obj_bench": bench(wood, metal, args.seed + 4),
        "obj_tree": tree(green, wood, args.seed + 5),
    }
    out = root / args.out
    out.mkdir(parents=True, exist_ok=True)
    for name, image in items.items():
        image.save(out / ("%s.png" % name))
        print("  %-24s %dx%d" % (name, image.width, image.height))
    print("")
    print("%d 点: %s" % (len(items), out.relative_to(config.ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
