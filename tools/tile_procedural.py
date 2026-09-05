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
FAMILIES = {
    "olive": (55, 95, 1.0),
    "warm": (20, 50, 0.16),
    "earth": (0, 45, 1.0),
    "green": (95, 180, 1.0),
    "indigo": (195, 250, 1.0),
    "neutral": (0, 360, 0.13),
}


def _hls(colour):
    return colorsys.rgb_to_hls(*[v / 255 for v in colour])


def family(palette: list, name: str) -> list:
    """パレットから系統を明度順に取り出す。**混ぜない。1系統だけを使う。**"""
    if name not in FAMILIES:
        raise SystemExit("未知の系統: %s / 既知: %s" % (name, ", ".join(sorted(FAMILIES))))
    low, high, max_s = FAMILIES[name]
    picked = [c for c in palette
              if low <= _hls(c)[0] * 360 <= high and _hls(c)[2] <= max_s]
    if name == "neutral":
        picked = [c for c in palette if _hls(c)[2] <= max_s]
    if not picked:
        raise SystemExit("系統 %s の色がパレットにありません" % name)
    return sorted(picked, key=lambda c: _hls(c)[1])


def render_field(ramp: list, size: int, seed: int, contrast: float,
                 octaves: int, base_cells: int, bias: float) -> Image.Image:
    """ノイズをランプへ写す。**ランプは1系統。色相は動かない。**"""
    field = procgen.fbm(size, octaves, seed=seed, base_cells=base_cells)
    image = Image.new("RGB", (size, size))
    px = image.load()
    steps = len(ramp)
    for y in range(size):
        for x in range(size):
            value = (field[y][x] - 0.5) * contrast + bias
            px[x, y] = ramp[max(0, min(steps - 1, int(value * steps)))]
    return image


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
    parser.add_argument("--contrast", type=float, default=1.30,
                        help="ランプのどこまで使うか（既定: 1.30）。**質感はここで出す**。")
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

    lower_ramp = family(palette, args.lower)
    upper_ramp = family(palette, args.upper)
    print("パレット  : %s（%d色）" % (args.palette, len(palette)))
    print("lower     : %s %d段  %s" % (args.lower, len(lower_ramp),
                                       " ".join("#%02X%02X%02X" % c for c in lower_ramp)))
    print("upper     : %s %d段  %s" % (args.upper, len(upper_ramp),
                                       " ".join("#%02X%02X%02X" % c for c in upper_ramp)))

    lower_field = snap(render_field(lower_ramp, args.size, args.seed + 11, args.contrast,
                                    args.octaves, args.base_cells, args.bias), palette)
    upper_field = snap(render_field(upper_ramp, args.size, args.seed + 23, args.contrast,
                                    args.octaves, args.base_cells, args.bias), palette)
    lower_tiles = slice_tiles(lower_field)
    upper_tiles = slice_tiles(upper_field)

    per_side = args.size // 32
    print("面        : %dx%d → %dx%d = %d枚（反復の周期は %dタイル）"
          % (args.size, args.size, per_side, per_side, len(lower_tiles), per_side))
    print("lower     : ざらつき %.2f  / upper : ざらつき %.2f"
          % (sum(roughness(t) for t in lower_tiles) / len(lower_tiles),
             sum(roughness(t) for t in upper_tiles) / len(upper_tiles)))
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
