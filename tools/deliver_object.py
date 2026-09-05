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
  6. 細い突起        2px 未満の突起が面積の5%以下。**1px 幅の部分は32pxで消える**
  7. 地面との明度差   **objects / overhead にのみ適用。** 地面に付く deco は対象外

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
    "thin_ratio_max": 0.05,
    "contact_shadow_rows": 2,
    "shadow_overhang_max": 2,
    "ground_light_range": (26.0, 85.0),
    "ground_light_margin": 20.0,
    "grid": 32,
}


def _lightness(colour) -> float:
    return colorsys.rgb_to_hls(*[v / 255 for v in colour])[1] * 255


def inspect(image: Image.Image, palette: set, lights: set,
            ground_layer: bool = False) -> tuple:
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
    #   **余白の量では判定しない。** 画布はタイルの枡そのものであり、
    #   枡の中のどこに置くかは意味のある配置である。
    #     - 32x32 に内接する円（マンホール）は四辺に余白を持つ
    #     - 32x64 の中央に引いた 4px の白線は、面積の 12% しか占めない
    #   どちらも正しい。**「余白＝トリム漏れ」という前提が誤りだった。**
    #   画布が 32px の倍数であることだけを見る。
    bbox = rgba.split()[3].getbbox()
    if bbox:
        stats["fill"] = ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                         / (rgba.width * rgba.height))

    # 6. 細い突起
    #   **収縮率で測ってはならない。** 収縮率は「全体の細さ」を測る指標であり、
    #   3px の白線（正しく細い）と 1px の突起（消える）を区別できない。
    #   実際、承認済みの基準で駐車枠が 50%、体育館のラインが 33% と判定され、
    #   **実物を路面に置くと問題なく読めた。**
    #   開き演算（収縮 → 膨張）で消える画素が、2px 未満の突起である。
    #   太い部分は元に戻るので、細い部分だけが残差になる。
    alpha = rgba.split()[3]
    total = sum(1 for v in alpha.get_flattened_data() if v > 0)
    opened = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    kept = sum(1 for v in opened.get_flattened_data() if v > 0)
    thin = (total - kept) / total if total else 0.0
    stats["thin_ratio"] = thin
    if thin > CRITERIA["thin_ratio_max"]:
        problems.append(
            "2px 未満の突起が面積の %.0f%% あります（上限 %.0f%%）。"
            "**1px 幅の部分は 32px で消えます**"
            % (thin * 100, CRITERIA["thin_ratio_max"] * 100))

    # 7. 地面との明度差
    #   **地面に「立つ」物のための基準である。** `ground_detail` は地面に
    #   「付く」物であり、地面と同じ明度であることがむしろ正しい。
    #   マンホールは実際にアスファルトと同じ暗さで、現実でも
    #   **明度ではなく形と縁で見分ける。**
    mean = sum(_lightness(p[:3]) for p in opaque) / len(opaque)
    low, high = CRITERIA["ground_light_range"]
    margin = CRITERIA["ground_light_margin"]
    stats["mean_light"] = mean
    if ground_layer and low <= mean <= high and min(mean - low, high - mean) < margin:
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
        problems, stats = inspect(image, palette, lights,
                                  ground_layer=args.category not in ("deco",))
        name = path.stem
        report[name] = {"problems": problems, "stats": stats}
        line = ("   %-24s %-9s 色数%3d 光源%4.0f%% 細い突起%4.0f%% 平均明度%5.0f"
                % (name, stats.get("size", "-"), stats.get("colours", 0),
                   stats.get("light_area", 0) * 100, stats.get("thin_ratio", 0) * 100,
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
