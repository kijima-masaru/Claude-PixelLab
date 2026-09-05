#!/usr/bin/env python3
"""_work のタイルセットを検査し、合格したものだけを assets/ へ納品する。

    python tools/deliver_tileset.py --project iwato --input _work/tile_soil_grass

**基準を満たさないものは納品させない。** 目視の承認を1本ずつ取る運用を
やめたため、機械が門番になる。基準は5つ（docs/PILOT_FINDINGS.md 第11・14節）。

    ざらつき            3.5〜6.0    質感の量
    帯域比              0.6 以下    斑の大きさ。**1を超えると迷彩に見える**
    格子の目立ちやすさ   0.35 以下   32px の格子が見えないこと
    パレット外           0色
    段数                主系統は6段以上（4段では段差が大きすぎる）

色相が1系統かどうかは機械では判定しきれない（素材によって系統が違う）ため、
**使用色の色相の広がり**で代用する。差し色を混ぜると必ず広がる。

納品物には base64 を持たせない。**PNG は Git LFS、メタデータは通常の
テキストとして管理する。** 両方に画像を持つと LFS の外に数十KB が載る。
"""

from __future__ import annotations

import argparse
import base64
import colorsys
import io
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402
from lib import procgen  # noqa: E402
from tile_from_texture import load_palette, roughness  # noqa: E402

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow が必要です: python -m pip install -r requirements.txt")


#: 納品の基準。**量産中に足さないこと。** 足すなら19本すべてに遡って適用が要る。
CRITERIA = {
    "roughness": (3.5, 6.0),
    "grain_ratio_max": 0.6,
    "grid_visibility_max": 0.35,
    "hue_spread_max": 90.0,     # 使用色の色相の広がり（度）。差し色を混ぜると広がる
    "ramp_steps_min": 6,
}


def _hue(colour) -> float:
    return colorsys.rgb_to_hls(*[v / 255 for v in colour])[0] * 360


def _saturation(colour) -> float:
    return colorsys.rgb_to_hls(*[v / 255 for v in colour])[2]


#: 色相の広がりを数えるときの最小占有率。これ未満の色は無視する。
#: **面積で重み付けしないと使えない。** 承認済みの tile_asphalt_curb は、
#: 占有率 0.06% の暖色2色のせいで色相の広がりが 183度 と判定された。
#: 0.06% は差し色ではなく、吸着の端数である。差し色は必ず 10% 以上を占める。
MIN_COVERAGE = 0.01


def hue_spread(counts: dict) -> float:
    """使用色の色相の広がり。**面積で重み付けする。**

    彩度の低い色は色相が定まらないので除き、占有率の低い色も除く。
    円環上の広がりなので、最も広い「隙間」を全周から引いて求める。
    """
    total = sum(counts.values()) or 1
    hues = sorted(_hue(c) for c, n in counts.items()
                  if _saturation(c) >= 0.08 and n / total >= MIN_COVERAGE)
    if len(hues) < 2:
        return 0.0
    gaps = [b - a for a, b in zip(hues, hues[1:])] + [hues[0] + 360 - hues[-1]]
    return 360.0 - max(gaps)


def field_of(tiles: list, per_side: int) -> Image.Image:
    """タイルの並びから面を組み立て、格子の目立ちやすさを測れるようにする。"""
    canvas = Image.new("RGB", (per_side * 32 * 2, per_side * 32 * 2))
    for y in range(per_side * 2):
        for x in range(per_side * 2):
            index = (y % per_side) * per_side + (x % per_side)
            canvas.paste(tiles[index % len(tiles)], (x * 32, y * 32))
    return canvas


def decode(entry: dict) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(entry["image"]["base64"]))).convert("RGB")


def inspect(payload: dict, palette: list) -> tuple:
    """(判定結果, 実測値) を返す。**問題があれば納品しない。**"""
    inner = payload["tileset"]
    problems, stats = [], {}

    wang = [decode(t) for t in inner["tiles"]]
    groups = {}
    if "supertile" in inner:
        per_side = inner["supertile"]["width"]
        for kind in ("lower", "upper"):
            groups[kind] = ([decode(t) for t in inner["supertile"][kind]], per_side)
    elif inner.get("alternatives"):
        for kind in ("lower", "upper"):
            variants = [decode(t) for t in inner["alternatives"][kind]]
            groups[kind] = (variants, 1)
    else:
        problems.append("変種も スーパータイルもありません。**16枚だけでは広い面が反復します。**")

    for kind, (tiles, per_side) in groups.items():
        rough = sum(roughness(t) for t in tiles) / len(tiles)
        grain = procgen.grain_ratio(field_of(tiles, per_side))
        grid = procgen.grid_visibility(field_of(tiles, per_side), period=max(per_side, 2))
        counts: dict = {}
        for tile in tiles:
            for pixel in tile.get_flattened_data():
                counts[pixel] = counts.get(pixel, 0) + 1
        spread = hue_spread(counts)
        steps = len(counts)
        stats[kind] = {"roughness": rough, "grain_ratio": grain,
                       "grid_visibility": grid, "hue_spread": spread, "colours": steps}
        low, high = CRITERIA["roughness"]
        if not low <= rough <= high:
            problems.append("%s: ざらつき %.2f が %.1f〜%.1f の外です" % (kind, rough, low, high))
        if grain > CRITERIA["grain_ratio_max"]:
            problems.append("%s: 帯域比 %.2f が %.1f を超えています。**斑が大きすぎ、迷彩に見えます**"
                            % (kind, grain, CRITERIA["grain_ratio_max"]))
        if grid > CRITERIA["grid_visibility_max"]:
            problems.append("%s: 格子の目立ちやすさ %.3f が %.2f を超えています"
                            % (kind, grid, CRITERIA["grid_visibility_max"]))
        if spread > CRITERIA["hue_spread_max"]:
            problems.append("%s: 色相の広がりが %.0f度 あります。**主系統は1つ、差し色なしです**"
                            % (kind, spread))

    outside = {p for t in wang for p in t.get_flattened_data()} - set(palette)
    if outside:
        problems.append("パレット外の色が %d 色あります" % len(outside))
    return problems, stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deliver_tileset.py",
        description="タイルセットを検査し、合格したものだけを assets/ へ納品する。")
    config.add_project_arg(parser)
    parser.add_argument("--input", required=True, metavar="PATH", help="_work のディレクトリ。")
    parser.add_argument("--name", help="納品名。省略時は入力ディレクトリ名。")
    parser.add_argument("--palette", default="palettes/iwato_colors_terrain.png")
    parser.add_argument("--note", default="", help="tileset.json に残す補足。")
    parser.add_argument("--command", default="", help="再現用のコマンドを記録する。")
    parser.add_argument("--force", action="store_true",
                        help="基準を満たさなくても納品する。**理由なく使わないこと。**")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config.load_project(args.project)
    root = config.project_dir(args.project)
    src = root / args.input
    payload = json.loads((src / "tileset.json").read_text(encoding="utf-8"))
    palette = load_palette(root / args.palette)
    name = args.name or src.name

    problems, stats = inspect(payload, palette)
    print("== %s" % name)
    for kind, s in stats.items():
        print("   %-6s ざらつき%5.2f  帯域比%5.2f  格子%6.3f  色相の広がり%5.0f度  色数%3d"
              % (kind, s["roughness"], s["grain_ratio"], s["grid_visibility"],
                 s["hue_spread"], s["colours"]))
    if problems:
        for problem in problems:
            print("   [NG] " + problem)
        if not args.force:
            print("   **納品しません。** 基準を満たしてから再実行してください。")
            return 1
        print("   [警告] --force により基準を無視して納品します。")

    dst = config.assets_dir(args.project) / "tilesets" / name
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    inner = payload["tileset"]
    meta = {"schema_version": 2, "name": name, "note": args.note,
            "source": {"command": args.command, "palette": args.palette},
            "measured": stats,
            "tile_size": inner["tile_size"], "terrain_types": inner["terrain_types"],
            "tiles": []}
    for tile in inner["tiles"]:
        decode(tile).save(dst / ("%s.png" % tile["name"]))
        meta["tiles"].append({"name": tile["name"], "file": tile["name"] + ".png",
                              "corners": tile["corners"]})
    if "supertile" in inner:
        st = inner["supertile"]
        meta["supertile"] = {"width": st["width"], "height": st["height"],
                             "order": st["order"],
                             "note": "**元の並び順で置くこと。** ランダムに置くと連続性が壊れる。",
                             "lower": [], "upper": []}
        for kind in ("lower", "upper"):
            for entry in st[kind]:
                decode(entry).save(dst / ("%s.png" % entry["name"]))
                meta["supertile"][kind].append({"name": entry["name"],
                                                "file": entry["name"] + ".png",
                                                "row": entry["row"], "col": entry["col"]})
    if inner.get("alternatives"):
        meta["alternatives"] = {"note": "ランダムに置いてよい。", "lower": [], "upper": []}
        for kind in ("lower", "upper"):
            for entry in inner["alternatives"][kind]:
                decode(entry).save(dst / ("%s.png" % entry["name"]))
                meta["alternatives"][kind].append({"name": entry["name"],
                                                   "file": entry["name"] + ".png"})
    (dst / "tileset.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    print("   納品: %s（PNG %d枚）"
          % (dst.relative_to(config.ROOT), len(list(dst.glob("*.png")))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
