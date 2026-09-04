#!/usr/bin/env python3
"""タイルセットを実際に並べて、接続が成立するかを確かめる。

    python tools/assemble_tileset.py --project iwato --input _work/<run_id>

**単体で綺麗でも接続で破綻すれば意味がない。** Wang タイルとして
16枚が継ぎ目なく繋がるかが本質であり、破綻はプロンプトではなく
アプローチの失敗である。

各タイルは corners（NW/NE/SW/SE がそれぞれ lower か upper）を持つ。
テスト用の地形マスクを作り、各セルの4隅の値に一致するタイルを選んで
敷き詰める。これが Wang タイルの正しい使い方であり、
**適当に並べたのでは接続の検証にならない。**
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow が必要です: python -m pip install -r requirements.txt")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="assemble_tileset.py",
        description="タイルセットの16タイルを地形マスクに従って敷き詰め、接続を確認する。",
    )
    config.add_project_arg(parser)
    parser.add_argument("--input", "-i", required=True, metavar="PATH",
                        help="tileset.json のあるディレクトリ（プロジェクト相対）。")
    parser.add_argument("--out", metavar="PATH",
                        help="出力 PNG。省略時は入力ディレクトリに assembled.png。")
    parser.add_argument("--scale", type=int, default=3, help="拡大率（既定: 3）。")
    parser.add_argument("--mask", default="island",
                        choices=["island", "road", "isolated", "checker"],
                        help="テスト用の地形マスク（既定: island）。")
    return parser


#: テスト用の地形マスク。1 が upper、0 が lower。
#: 角の全組み合わせが現れるように作ってある。
MASKS = {
    # 島状。凸角・凹角・直線・単独がすべて出る
    "island": [
        "0000000000",
        "0011111000",
        "0011111000",
        "0011001100",
        "0011001100",
        "0001111100",
        "0000110000",
        "0000000000",
    ],
    # 道路状。縁石が細い帯として現れる、実際の使い方に近い形
    "road": [
        "0000000000",
        "1111111111",
        "1111111111",
        "0000000000",
        "0000000000",
        "1110000111",
        "1110000111",
        "0000000000",
    ],
    # 孤立点。**1点の物をタイルセットで作れるかを検証するためのマスク。**
    # 角が1つだけ upper のタイルを 2x2 で並べると、上地形の丸い塊が
    # 1つだけ現れる。電柱のような点の物が作れるかはこれで分かる。
    "isolated": [
        "0000000000",
        "0010001000",
        "0000000000",
        "0001000100",
        "0000000000",
        "0010001000",
        "0000000000",
        "0000000000",
    ],
    # 市松。最も過酷な条件で、全16パターンが確実に出る
    "checker": [
        "0101010101",
        "1010101010",
        "0101010101",
        "1010101010",
        "0110100101",
        "1001011010",
        "0011001100",
        "1100110011",
    ],
}


def load_tiles(path: Path) -> tuple:
    """tileset.json からタイルを読む。(タイル一覧, タイルサイズ) を返す。"""
    import base64

    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    inner = data.get("tileset") or data
    tiles = inner.get("tiles") or []
    if not tiles:
        raise SystemExit("タイルが入っていません: " + str(path))

    out = []
    for t in tiles:
        # 完成品（assets/）のメタデータは base64 を持たず、隣の PNG を指す。
        # base64 をテキストで二重に持つと、LFS の外で数十KB が git に載るため。
        if t.get("file"):
            out.append({
                "id": t.get("id"),
                "name": t.get("name"),
                "corners": t.get("corners") or {},
                "image": (path.parent / t["file"]).read_bytes(),
            })
            continue
        img = t.get("image") or {}
        b64 = img.get("base64") if isinstance(img, dict) else img
        if not b64:
            continue
        out.append({
            "id": t.get("id"),
            "name": t.get("name"),
            "corners": t.get("corners") or {},
            "image": base64.b64decode(b64),
        })
    size = inner.get("tile_size") or {"width": 32, "height": 32}
    return out, (size["width"], size["height"])


def corner_key(nw: str, ne: str, sw: str, se: str) -> tuple:
    return (nw, ne, sw, se)


def index_tiles(tiles: list) -> dict:
    """corners の組み合わせからタイルを引けるようにする。"""
    table = {}
    for t in tiles:
        c = t["corners"]
        if not all(k in c for k in ("NW", "NE", "SW", "SE")):
            continue
        table[corner_key(c["NW"], c["NE"], c["SW"], c["SE"])] = t
    return table


def assemble(tiles: list, tile_size: tuple, mask: list) -> tuple:
    """地形マスクに従って敷き詰める。(画像, 欠落した組み合わせ) を返す。"""
    import io

    table = index_tiles(tiles)
    tw, th = tile_size
    rows = len(mask) - 1
    cols = len(mask[0]) - 1
    canvas = Image.new("RGBA", (cols * tw, rows * th), (0, 0, 0, 0))
    missing = []

    def terrain(r: int, c: int) -> str:
        return "upper" if mask[r][c] == "1" else "lower"

    for r in range(rows):
        for c in range(cols):
            key = corner_key(terrain(r, c), terrain(r, c + 1),
                             terrain(r + 1, c), terrain(r + 1, c + 1))
            tile = table.get(key)
            if tile is None:
                missing.append(key)
                continue
            img = Image.open(io.BytesIO(tile["image"])).convert("RGBA")
            canvas.paste(img, (c * tw, r * th), img)
    return canvas, missing


def _upper_ratio(tile: dict) -> float:
    """そのタイルの角のうち upper が占める割合。0.0〜1.0。

    1点の物を作る場合、使えるのは upper が少ないタイル（孤立した角）と
    upper だけのタイルに限られる。中間のタイルは地形の境界用であり、
    点の物には使い道がない。その判断材料にする。
    """
    c = tile.get("corners") or {}
    vals = [c.get(k) for k in ("NW", "NE", "SW", "SE")]
    return sum(1 for v in vals if v == "upper") / 4.0


def contact_sheet(tiles: list, tile_size: tuple, scale: int) -> Image.Image:
    """16タイルを単体で並べた一覧を作る。"""
    import io

    tw, th = tile_size
    cols = 8
    rows = (len(tiles) + cols - 1) // cols
    pad = 4
    sheet = Image.new("RGBA", (cols * (tw + pad) + pad, rows * (th + pad) + pad),
                      (26, 26, 30, 255))
    for i, t in enumerate(tiles):
        img = Image.open(io.BytesIO(t["image"])).convert("RGBA")
        x = pad + (i % cols) * (tw + pad)
        y = pad + (i // cols) * (th + pad)
        sheet.paste(img, (x, y), img)
        t["_upper_ratio"] = _upper_ratio(t)
    return sheet.resize((sheet.width * scale, sheet.height * scale), Image.NEAREST)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config.load_project(args.project)
    base = config.project_dir(args.project) / args.input
    path = base if base.is_file() else base / "tileset.json"
    if not path.is_file():
        raise SystemExit("tileset.json が見つかりません: " + str(path))

    tiles, tile_size = load_tiles(path)
    print("タイル数    : %d" % len(tiles))
    print("タイルサイズ: %dx%d" % tile_size)

    table = index_tiles(tiles)
    print("角の組み合わせ: %d 種" % len(table))
    for t in tiles:
        c = t["corners"]
        print("  %-10s NW=%-5s NE=%-5s SW=%-5s SE=%-5s"
              % (t.get("name"), c.get("NW"), c.get("NE"), c.get("SW"), c.get("SE")))

    mask = MASKS[args.mask]
    canvas, missing = assemble(tiles, tile_size, mask)
    if missing:
        print("")
        print("[警告] マスクが要求する組み合わせのうち %d 箇所にタイルがありません:"
              % len(missing))
        for key in sorted(set(missing)):
            print("    NW=%s NE=%s SW=%s SE=%s" % key)

    out = Path(args.out) if args.out else (base / "assembled.png")
    big = canvas.resize((canvas.width * args.scale, canvas.height * args.scale),
                        Image.NEAREST)
    big.save(out)
    print("")
    print("")
    print("角の upper 比率ごとのタイル数（1点の物では偏りが問題になる）:")
    from collections import Counter
    dist = Counter(_upper_ratio(t) for t in tiles)
    for r in sorted(dist):
        print("    upper %d/4 : %2d 枚" % (int(r * 4), dist[r]))
    print("")
    print("敷き詰め: %s（マスク=%s, %dx%d を %d倍）"
          % (out.relative_to(config.ROOT) if out.is_relative_to(config.ROOT) else out,
             args.mask, canvas.width, canvas.height, args.scale))

    # 暗い素材は、明背景と暗背景の両方に置かないと
    # 透過部分と暗部の区別がつかない。両方を並べて出す。
    for name, bg in (("_on_dark", (26, 26, 30, 255)), ("_on_light", (222, 222, 226, 255))):
        plate = Image.new("RGBA", big.size, bg)
        plate.alpha_composite(big)
        plate.save(out.with_name(out.stem + name + ".png"))

    sheet_path = out.with_name(out.stem + "_tiles.png")
    contact_sheet(tiles, tile_size, args.scale).save(sheet_path)
    print("タイル一覧: %s"
          % (sheet_path.relative_to(config.ROOT)
             if sheet_path.is_relative_to(config.ROOT) else sheet_path))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
