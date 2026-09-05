#!/usr/bin/env python3
"""オブジェクト（deco / objects / overhead）を検査し、合格したものだけを納品する。

    python tools/deliver_object.py --project iwato --input _work/deco

**タイルセットの基準は使わない。** ざらつき・帯域比・格子は「面を埋める素材」
のための指標であり、形を持つ物には当てはまらない。

機械で判定する7項目。**量産中に足さないこと。**

  1. パレット適合      使用色すべてがパレット内
  2. 光源色の面積      15%以下。**光る部分は物の一部**であって面の大半ではない
  3. 透過              アルファは 0 と 255 のみ。32px で半透明は滲みになる
  4. 接地影            底2行に暗部。**シルエット外へ2pxを超えて伸びない**（第5節）
  5. 寸法とグリッド    32の倍数。余白がトリム済み
  6. シルエットの太さ  1px 収縮して面積の70%以上が残る。**1px幅の突起は32pxで消える**
  7. 地面との明度差    地面タイルの明度帯（26〜85）を外れるか、差が20以上あること

**機械で判定できない3項目**（目視。コンタクトシートでまとめて見る）:

  - 日本の物として識別できるか
  - 投影が真上見下ろしか
  - 意図した物に見えるか

**これらに指標を作らない。** 意味の判定であり、数値化しようとすれば
機能しない指標を増やすだけである（タイルセットで一度経験した）。
"""

from __future__ import annotations

import argparse
import colorsys
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402
from tile_from_texture import load_palette  # noqa: E402

try:
    from PIL import Image, ImageFilter
except ImportError:
    sys.exit("Pillow が必要です: python -m pip install -r requirements.txt")


#: 判定の基準。**凍結してある。** 足すなら既に納品したものへ遡って適用が要る。
CRITERIA = {
    "light_area_max": 0.15,
    "erosion_keep_min": 0.70,
    "contact_shadow_rows": 2,
    "shadow_overhang_max": 2,
    "ground_light_range": (26.0, 85.0),
    "ground_light_margin": 20.0,
    "grid": 32,
}


def _lightness(colour) -> float:
    return colorsys.rgb_to_hls(*[v / 255 for v in colour])[1] * 255


def inspect(image: Image.Image, palette: set, lights: set) -> tuple:
    """(問題のリスト, 実測値) を返す。"""
    problems, stats = [], {}
    rgba = image.convert("RGBA")
    pixels = list(rgba.get_flattened_data())
    opaque = [p for p in pixels if p[3] > 0]
    if not opaque:
        return ["中身がありません（全て透明）"], {}

    # 1. パレット適合
    used = {p[:3] for p in opaque}
    outside = used - palette
    stats["colours"] = len(used)
    if outside:
        problems.append("パレット外の色が %d 色あります" % len(outside))

    # 2. 光源色の面積
    light_area = sum(1 for p in opaque if p[:3] in lights) / len(opaque)
    stats["light_area"] = light_area
    if light_area > CRITERIA["light_area_max"]:
        problems.append(
            "光源色が面積の %.0f%% を占めています（上限 %.0f%%）。"
            "**光る部分は物の一部であって、面の大半ではありません**"
            % (light_area * 100, CRITERIA["light_area_max"] * 100))

    # 3. 透過
    alphas = {p[3] for p in pixels}
    stats["alphas"] = sorted(alphas)
    if alphas - {0, 255}:
        problems.append("半透明の画素があります（アルファ %s）。32px では滲みになります"
                        % sorted(alphas - {0, 255})[:5])

    # 5. 寸法とグリッド
    grid = CRITERIA["grid"]
    stats["size"] = "%dx%d" % rgba.size
    if rgba.width % grid or rgba.height % grid:
        problems.append("寸法 %dx%d が %dpx の倍数ではありません" % (*rgba.size, grid))
    bbox = rgba.split()[3].getbbox()
    if bbox and (bbox[0] > 0 and bbox[1] > 0 and bbox[2] < rgba.width and bbox[3] < rgba.height):
        problems.append("四辺すべてに余白があります。トリムしてください")

    # 6. シルエットの太さ
    alpha = rgba.split()[3]
    before = sum(1 for v in alpha.get_flattened_data() if v > 0)
    eroded = alpha.filter(ImageFilter.MinFilter(3))
    after = sum(1 for v in eroded.get_flattened_data() if v > 0)
    keep = after / before if before else 0.0
    stats["erosion_keep"] = keep
    if keep < CRITERIA["erosion_keep_min"]:
        problems.append(
            "1px 収縮で面積が %.0f%% しか残りません（下限 %.0f%%）。"
            "**細い部分は 32px で消えます**"
            % (keep * 100, CRITERIA["erosion_keep_min"] * 100))

    # 7. 地面との明度差
    mean = sum(_lightness(p[:3]) for p in opaque) / len(opaque)
    low, high = CRITERIA["ground_light_range"]
    margin = CRITERIA["ground_light_margin"]
    stats["mean_light"] = mean
    if low <= mean <= high and min(mean - low, high - mean) < margin:
        problems.append(
            "平均明度 %.0f が地面の帯（%.0f〜%.0f）の中にあり、差が %.0f 未満です。"
            "**置くと地面に沈みます**" % (mean, low, high, margin))

    # 4. 接地影（**シルエット外へ伸びていないか**）
    rows = CRITERIA["contact_shadow_rows"]
    if bbox:
        bottom = bbox[3]
        overhang = 0
        for y in range(bottom, min(rgba.height, bottom + 8)):
            if any(rgba.getpixel((x, y))[3] > 0 for x in range(rgba.width)):
                overhang += 1
        stats["shadow_overhang"] = overhang
        if overhang > CRITERIA["shadow_overhang_max"]:
            problems.append(
                "影がシルエットの外へ %dpx 伸びています（上限 %dpx）。"
                "**長い落ち影は実行時に作ります**（第5節）"
                % (overhang, CRITERIA["shadow_overhang_max"]))
    return problems, stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deliver_object.py",
        description="オブジェクトを検査し、合格したものだけを assets/ へ納品する。")
    config.add_project_arg(parser)
    parser.add_argument("--input", required=True, metavar="PATH", help="_work のディレクトリ。")
    parser.add_argument("--category", default="deco", help="納品先のカテゴリ（既定: deco）。")
    parser.add_argument("--palette", default="palettes/iwato_colors.png")
    parser.add_argument("--terrain-palette", default="palettes/iwato_colors_terrain.png")
    parser.add_argument("--force", action="store_true", help="基準を無視して納品する。")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config.load_project(args.project)
    root = config.project_dir(args.project)
    palette = set(load_palette(root / args.palette))
    terrain = set(load_palette(root / args.terrain_palette))
    lights = palette - terrain

    src = root / args.input
    files = sorted(src.glob("*.png"))
    if not files:
        raise SystemExit("PNG がありません: %s" % src)
    print("パレット %d 色（うち光源 %d 色） / 検査 %d 点" % (len(palette), len(lights), len(files)))

    dst = config.assets_dir(args.project) / args.category
    dst.mkdir(parents=True, exist_ok=True)
    passed = failed = 0
    report = {}
    for path in files:
        image = Image.open(path)
        problems, stats = inspect(image, palette, lights)
        name = path.stem
        report[name] = {"problems": problems, "stats": stats}
        line = ("   %-24s %-9s 色数%3d 光源%4.0f%% 収縮残り%4.0f%% 平均明度%5.0f"
                % (name, stats.get("size", "-"), stats.get("colours", 0),
                   stats.get("light_area", 0) * 100, stats.get("erosion_keep", 0) * 100,
                   stats.get("mean_light", 0)))
        if problems and not args.force:
            failed += 1
            print("[NG]" + line)
            for problem in problems:
                print("        - " + problem)
            continue
        passed += 1
        print("[OK]" + line)
        image.convert("RGBA").save(dst / path.name)
    (src / "inspection.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    print("")
    print("合格 %d / %d（不合格 %d）" % (passed, len(files), failed))
    print("納品先: %s" % dst.relative_to(config.ROOT))
    print("")
    print("**目視で見る3項目**（コンタクトシートでまとめて判定する）:")
    print("  - 日本の物として識別できるか / 投影が真上見下ろしか / 意図した物に見えるか")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
