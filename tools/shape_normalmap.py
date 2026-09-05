#!/usr/bin/env python3
"""**形からノーマルマップを起こす。** 立ち物のためのもの。

    python tools/shape_normalmap.py --project iwato --category objects

`normalmap.py` は**輝度を高さとみなす**。地面にはこれで正しい。
アスファルトの粒や草の斑は、実際に明るい所が出っ張っているからである。

**立ち物には通用しない。** PixelLab が描き込んだ陰影は「上から光が当たった絵」
であって凹凸ではない。輝度から法線を起こすと、**描かれた影の勾配**を
凹凸として読んでしまう。自販機の暗い取り出し口が「深い穴」になり、
明るい発光面が「山」になる。実際にはどちらも平らな面である。
結果として、ライトを当てても立体感は増えない（第22節の確認で観測した）。

**ここでは輪郭からの距離を高さとする。** シルエットの中心ほど手前、
縁ほど奥へ回り込む――枕（pillow）のような法線を作る。これなら
「左から光が当たれば左の縁が明るい」という、**光の向きに応じた陰影**が出る。

    高さ h = sin(π/2 · min(d/R, 1))      d は輪郭からの距離、R は回り込みの幅

輝度から起こした細部を**少しだけ**混ぜる（既定 0.25）。板の目地や
格子は実際に凹んでいるので、完全に捨てるのは惜しい。

Y 軸は Godot 用に反転する（`normalmap.py` と同じ。docs/NORMALMAP.md）。
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow が必要です: python -m pip install -r requirements.txt")

#: 出力の接尾辞。**`_n` とは別に置く。** 地面用と立ち物用を取り違えないため。
SHAPE_SUFFIX = "_s"

#: チャンファ距離。近似だが、32〜128px では誤差が見た目に出ない。
_ORTHO, _DIAG = 1.0, 1.41421356


def distance_inside(alpha: list, w: int, h: int) -> list:
    """不透明領域の各画素について、**輪郭までの距離**を返す。

    2パスのチャンファ変換。画布の外は「輪郭の外」として扱う
    （端で切れている物は、その端が縁になる）。
    """
    big = float(w + h)
    dist = [0.0 if a == 0 else big for a in alpha]

    def get(x, y):
        if x < 0 or y < 0 or x >= w or y >= h:
            return 0.0
        return dist[y * w + x]

    for y in range(h):                      # 前方（左上 → 右下）
        for x in range(w):
            i = y * w + x
            if dist[i] == 0.0:
                continue
            dist[i] = min(dist[i],
                          get(x - 1, y) + _ORTHO, get(x, y - 1) + _ORTHO,
                          get(x - 1, y - 1) + _DIAG, get(x + 1, y - 1) + _DIAG)
    for y in range(h - 1, -1, -1):          # 後方（右下 → 左上）
        for x in range(w - 1, -1, -1):
            i = y * w + x
            if dist[i] == 0.0:
                continue
            dist[i] = min(dist[i],
                          get(x + 1, y) + _ORTHO, get(x, y + 1) + _ORTHO,
                          get(x + 1, y + 1) + _DIAG, get(x - 1, y + 1) + _DIAG)
    return dist


def shape_normalmap(image: Image.Image, radius: float = 7.0,
                    detail: float = 0.25, strength: float = 1.0,
                    flip_y: bool = True) -> Image.Image:
    """形（シルエット）から法線を作る。輝度の勾配を `detail` の重みで混ぜる。"""
    rgba = image.convert("RGBA")
    w, h = rgba.size
    alpha = list(rgba.getchannel("A").get_flattened_data())
    lum = [v / 255.0 for v in rgba.convert("L").get_flattened_data()]
    dist = distance_inside(alpha, w, h)

    # 距離 → 高さ。**縁で急に、中央で緩やかに**立ち上がる曲面にする。
    height = [0.0] * (w * h)
    for i, d in enumerate(dist):
        if alpha[i] == 0:
            continue
        height[i] = math.sin(min(d / radius, 1.0) * math.pi * 0.5)

    def sample(field, x, y):
        x = min(max(x, 0), w - 1)
        y = min(max(y, 0), h - 1)
        i = y * w + x
        return 0.0 if alpha[i] == 0 else field[i]

    out = Image.new("RGBA", (w, h), (128, 128, 255, 0))
    px = out.load()
    for y in range(h):
        for x in range(w):
            if alpha[y * w + x] == 0:
                continue
            dx = (sample(height, x + 1, y) - sample(height, x - 1, y)) * 0.5
            dy = (sample(height, x, y + 1) - sample(height, x, y - 1)) * 0.5
            if detail > 0.0:
                dx += (sample(lum, x + 1, y) - sample(lum, x - 1, y)) * 0.5 * detail
                dy += (sample(lum, x, y + 1) - sample(lum, x, y - 1)) * 0.5 * detail
            nx = -dx * strength * radius * 0.5
            ny = -dy * strength * radius * 0.5
            if flip_y:
                ny = -ny
            length = math.sqrt(nx * nx + ny * ny + 1.0)
            px[x, y] = (int(round((nx / length * 0.5 + 0.5) * 255)),
                        int(round((ny / length * 0.5 + 0.5) * 255)),
                        int(round((1.0 / length * 0.5 + 0.5) * 255)),
                        255)
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shape_normalmap.py",
        description="立ち物のノーマルマップを、輝度ではなく形から起こす。")
    config.add_project_arg(parser)
    parser.add_argument("--category", default="objects", help="対象カテゴリ（既定: objects）。")
    parser.add_argument("--radius", type=float, default=7.0,
                        help="縁の回り込みの幅（画素。既定: 7）。")
    parser.add_argument("--detail", type=float, default=0.25,
                        help="輝度から起こした細部を混ぜる重み（既定: 0.25）。")
    parser.add_argument("--strength", type=float, default=1.0)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load_project(args.project)
    directory = config.assets_dir(cfg["id"]) / args.category
    if not directory.is_dir():
        raise SystemExit("ありません: %s" % directory)

    targets = sorted(p for p in directory.rglob("*.png")
                     if not p.stem.endswith(("_n", SHAPE_SUFFIX)))
    print("対象 %d 点 / 回り込み %.1fpx / 細部の重み %.2f"
          % (len(targets), args.radius, args.detail))
    written = 0
    for path in targets:
        out = path.with_name(path.stem + SHAPE_SUFFIX + path.suffix)
        if out.exists() and not args.overwrite:
            continue
        image = shape_normalmap(Image.open(path), radius=args.radius,
                                detail=args.detail, strength=args.strength)
        image.save(out)
        written += 1
    print("形からのノーマルマップ %d 枚。API コスト $0.00" % written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
