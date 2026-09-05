#!/usr/bin/env python3
"""画面の影を**測る**。目測で決めない（PILOT_FINDINGS 第29節）。

    # 1枚の絵の中で、暗い側と明るい側の明度比を測る（参考画像などに使う）
    python tools/measure_shadow.py split IMAGE --box 560,60,1150,520

    # 「影あり」と「影なし」の同じ絵を比べる（自分の画面に使う）
    python tools/measure_shadow.py pair SHADOWED PLAIN --box 0,170,640,356

**`split` と `pair` は測るものが違う。** 混同しないこと。

`split` は「帯ぜんたいの下位20% / 上位20%」で測る。影を外した絵が
手に入らない画像（他所の画面）にはこれしかない。**ただし下位20%には
「影」ではなく「光が届いていないだけの場所」が入る。** 自分の画面に
使うと、環境光を下げても比が動かず、直したかどうかが分からない。

`pair` は**影を外した同じ絵**を基準に、暗くなった画素だけを影とみなす。
自分の画面はこちらで測る。`godot_preview` の `--levels` が両方を撮る。

参考画像は `refs/` にある。**API へは送らない。ここで読むだけである。**
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow が必要です: python -m pip install -r requirements.txt")

#: 影とみなす明度の下がり幅。これ未満は縁のゆらぎとして捨てる。
SHADOW_DROP = 10.0


def lum(c) -> float:
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def parse_box(text: str, image: Image.Image) -> tuple:
    if not text:
        return (0, 0, image.width, image.height)
    x0, y0, x1, y1 = (int(v) for v in text.split(","))
    return (x0, y0, x1, y1)


def measure_split(path: Path, box: str) -> None:
    im = Image.open(path).convert("RGB")
    x0, y0, x1, y1 = parse_box(box, im)
    vals = sorted(lum(c) for c in im.crop((x0, y0, x1, y1)).get_flattened_data())
    n = len(vals)
    dark = sum(vals[: n // 5]) / (n // 5)
    light = sum(vals[-(n // 5):]) / (n // 5)
    print("%s  %dx%d  範囲 %d,%d-%d,%d" % (path.name, im.width, im.height, x0, y0, x1, y1))
    print("  影の芯（下位20%%）%.1f / 日向の芯（上位20%%）%.1f" % (dark, light))
    print("  **明度比 %.3f**" % (dark / light))


def measure_pair(shadowed: Path, plain: Path, box: str) -> None:
    a = Image.open(shadowed).convert("RGB")
    b = Image.open(plain).convert("RGB")
    if a.size != b.size:
        raise SystemExit("2枚の大きさが違います: %s / %s" % (a.size, b.size))
    x0, y0, x1, y1 = parse_box(box, a)
    sp = list(a.crop((x0, y0, x1, y1)).get_flattened_data())
    bp = list(b.crop((x0, y0, x1, y1)).get_flattened_data())
    inside, outside = [], []
    for ca, cb in zip(sp, bp):
        la, lb = lum(ca), lum(cb)
        (inside if lb - la > SHADOW_DROP else outside).append(la)
    if not inside:
        print("影が見つかりません（2枚が同じか、範囲に影がありません）")
        return
    inside.sort()
    half = max(1, len(inside) // 2)
    core = sum(inside[:half]) / half
    mi = sum(inside) / len(inside)
    mo = sum(outside) / len(outside) if outside else 0.0
    print("%s ← %s  範囲 %d,%d-%d,%d" % (shadowed.name, plain.name, x0, y0, x1, y1))
    print("  影の中 %.1f（芯 %.1f） / 影の外 %.1f / 影の面積 %.0f%%"
          % (mi, core, mo, 100 * len(inside) / len(sp)))
    print("  **明度比 %.3f（芯で %.3f）**" % (mi / mo, core / mo))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="measure_shadow.py", description="画面の影の明度比を測る。")
    sub = parser.add_subparsers(dest="mode", required=True)
    s = sub.add_parser("split", help="1枚の絵の中で下位20%%と上位20%%を比べる。")
    s.add_argument("image", type=Path)
    s.add_argument("--box", default="", metavar="X0,Y0,X1,Y1")
    q = sub.add_parser("pair", help="影ありと影なしの同じ絵を比べる。**自分の画面はこちら**")
    q.add_argument("shadowed", type=Path)
    q.add_argument("plain", type=Path)
    q.add_argument("--box", default="", metavar="X0,Y0,X1,Y1")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "split":
        measure_split(args.image, args.box)
    else:
        measure_pair(args.shadowed, args.plain, args.box)
    return 0


if __name__ == "__main__":
    sys.exit(main())
