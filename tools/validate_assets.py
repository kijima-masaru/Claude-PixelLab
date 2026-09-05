#!/usr/bin/env python3
"""完成品が品質基準を満たしているかを検査する。

    python tools/validate_assets.py --project iwato
    python tools/validate_assets.py --project iwato --category tilesets --strict

検査基準は projects/<id>/project.yaml から読む。基準の定義は
docs/CONVENTIONS.md の「素材の品質基準」を参照。

失敗を握り潰さない。違反は全て列挙し、終了コードで示す。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config, imageops  # noqa: E402

CHECKS = ("palette", "grid", "alpha", "size", "layout")

#: 中間生成物に付く名前。assets/ に現れてはならない。
#: 敷き詰めの確認画像（tools/assemble_tileset.py の出力）が
#: 手作業で assets/ にコピーされる事故が実際に起きたため、名前で検出する。
#: 1点が複数ファイルになるカテゴリ。ここだけ素材名のディレクトリを要求する。
MULTI_FILE_CATEGORIES = ("tilesets",)

INTERMEDIATE_STEMS = ("assembled", "assembled_on_dark", "assembled_on_light",
                      "assembled_tiles", "island", "island_on_dark",
                      "island_on_light", "island_tiles",
                      "field_lower", "field_upper", "contact_sheet")

#: ノーマルマップの接尾辞。法線の色はパレット外になるのが正しいため、
#: パレット検査の対象から自動的に外す（グリッドとサイズは検査する）。
NORMALMAP_SUFFIX = "_n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate_assets.py",
        description="完成品のパレット適合・グリッド・透明度・サイズを検査する。",
    )
    config.add_project_arg(parser)
    parser.add_argument("--category", "-c", help="検査対象カテゴリ。省略時は全カテゴリ。")
    parser.add_argument("--path", help="単一ファイル／ディレクトリを検査する（プロジェクト相対）。")
    parser.add_argument("--check", nargs="+", choices=CHECKS, default=list(CHECKS),
                        metavar="NAME", help="実行する検査（既定: " + " ".join(CHECKS) + "）。")
    parser.add_argument("--strict", action="store_true",
                        help="警告も失敗として扱う（CI 用）。")
    parser.add_argument("--quiet", action="store_true", help="違反のみを出力する。")
    return parser


def check_palette(image, palette, max_colors: int) -> list:
    """使用色がパレット内かつ max_colors 以下かを検査する。"""
    problems = []
    used = imageops.count_colors(image)
    if len(used) > max_colors:
        problems.append("色数が上限を超えています: %d 色 > %d 色" % (len(used), max_colors))
    if palette:
        allowed = set(palette)
        outside = sorted(used - allowed)
        if outside:
            sample = ", ".join("#%02X%02X%02X" % c for c in outside[:6])
            problems.append(
                "パレット外の色が %d 色あります: %s%s"
                % (len(outside), sample, " …" if len(outside) > 6 else "")
            )
    return problems


def check_grid(image, tile_size: int) -> list:
    """寸法が tile_size の倍数かを検査する。"""
    w, h = image.size
    if not imageops.is_grid_aligned(image, tile_size):
        return ["寸法が %dpx の倍数ではありません: %dx%d" % (tile_size, w, h)]
    return []


def check_alpha(image) -> list:
    """半透明画素の有無を検査する（0 か 255 のみ許容）。"""
    count = imageops.semi_transparent_pixels(image)
    if count:
        return ["半透明画素が %d 個あります（アルファは 0 か 255 のみ許容）" % count]
    return []


def check_size(image, cfg: dict) -> list:
    """基準解像度に対して大きすぎないかを検査する。"""
    res = cfg["canvas"]["base_resolution"]
    limit_w, limit_h = res["width"] * 4, res["height"] * 4
    w, h = image.size
    if w > limit_w or h > limit_h:
        return ["基準解像度の4倍を超えています: %dx%d > %dx%d" % (w, h, limit_w, limit_h)]
    return []


def check_layout(cfg: dict) -> list:
    """assets/ の構造そのものを検査する。**画像1枚ずつでは気づけない事故を拾う。**

    見るのは2つ。

      1. **1点が複数ファイルになるカテゴリで、直下に緩い PNG が無いか。**
         タイルセットは16枚＋変種で1点なので `<素材名>/` にまとめる。
         **deco / objects のように1点1ファイルのカテゴリは直下でよい**
         （素材ごとにディレクトリを作っても意味が無い）
      2. **中間生成物の名前を持つファイルが無いか。**
         `assembled*.png` などは敷き詰めの確認用であって完成品ではない

    実際に、却下したタイルセットの確認画像20枚が `assets/tilesets/` 直下に
    残っていた。素材が増えれば埋もれる。ゆえにコードで見張る。
    """
    problems = []
    assets = config.assets_dir(cfg["id"])
    if not assets.is_dir():
        return problems
    for category in sorted(cfg["asset_categories"]):
        directory = assets / category
        if not directory.is_dir():
            continue
        if category in MULTI_FILE_CATEGORIES:
            for path in sorted(p for p in directory.iterdir()
                               if p.is_file() and p.suffix.lower() == ".png"):
                problems.append(
                    "%s: カテゴリ直下に PNG があります。完成品は素材名のディレクトリへ入れること"
                    % path.relative_to(config.ROOT))
        for path in sorted(directory.rglob("*.png")):
            if path.stem in INTERMEDIATE_STEMS:
                problems.append(
                    "%s: 中間生成物の名前です。**assets/ に確認画像を置かないこと**"
                    % path.relative_to(config.ROOT))
    return problems


def collect_targets(cfg: dict, args: argparse.Namespace) -> list:
    project = config.project_dir(cfg["id"])
    if args.path:
        base = project / args.path
        if base.is_file():
            return [base]
        if base.is_dir():
            return sorted(base.rglob("*.png"))
        raise SystemExit("対象が見つかりません: " + str(base))

    categories = [args.category] if args.category else list(cfg["asset_categories"])
    unknown = [c for c in categories if c not in cfg["asset_categories"]]
    if unknown:
        raise SystemExit(
            "未知のカテゴリ: " + ", ".join(unknown) + " / 既知: " + ", ".join(cfg["asset_categories"])
        )
    targets = []
    for category in categories:
        directory = config.assets_dir(cfg["id"]) / category
        if directory.is_dir():
            targets.extend(sorted(directory.rglob("*.png")))
    return targets


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load_project(args.project)

    palette = None
    palette_label = "未設定（色数上限のみ検査）"
    rel = cfg["palette"].get("file")
    if rel:
        path = config.project_dir(cfg["id"]) / rel
        if not path.is_file():
            raise SystemExit("パレットファイルが見つかりません: " + str(path))
        palette = imageops.load_palette(path)
        palette_label = str(rel) + "（" + str(len(palette)) + "色）"

    layout_problems = check_layout(cfg) if "layout" in args.check else []

    targets = collect_targets(cfg, args)
    tile = cfg["canvas"]["tile_size"]
    max_colors = cfg["palette"]["max_colors"]

    if not args.quiet:
        print("対象      : " + config.describe(cfg))
        print("パレット  : " + palette_label)
        print("実行検査  : " + ", ".join(args.check))
        print("判定基準  : パレット<=%d色 / グリッド%dpx / 半透明画素なし" % (max_colors, tile))
        print("検査枚数  : " + str(len(targets)))
        print("")

    if layout_problems:
        print("[NG] assets/ の構造")
        for problem in layout_problems:
            print("     - " + problem)
        print("")

    if not targets:
        print("検査対象の完成品がありません。")
        return 1 if layout_problems else 0

    failed = len(layout_problems)
    for path in targets:
        image = imageops.load_rgba(path)
        is_normalmap = path.stem.endswith(NORMALMAP_SUFFIX)
        problems = []
        # 法線の色はパレット外になるのが正しいので、パレット検査から外す。
        # 半透明も法線では意味が違うため見ない。グリッドとサイズは検査する。
        if "palette" in args.check and not is_normalmap:
            problems += check_palette(image, palette, max_colors)
        if "grid" in args.check:
            problems += check_grid(image, tile)
        if "alpha" in args.check and not is_normalmap:
            problems += check_alpha(image)
        if "size" in args.check:
            problems += check_size(image, cfg)

        rel_path = path.relative_to(config.ROOT)
        if problems:
            failed += 1
            print("[NG] " + str(rel_path))
            for problem in problems:
                print("     - " + problem)
        elif not args.quiet:
            used = len(imageops.count_colors(image))
            note = "  ※法線: パレット/透明度の検査は対象外" if is_normalmap else ""
            print("[OK] %s  %dx%d  %d色%s"
                  % (rel_path, image.width, image.height, used, note))

    print("")
    if failed:
        print("失敗: %d / %d 枚が基準を満たしていません。" % (failed, len(targets)))
        return 1
    print("合格: %d 枚すべてが基準を満たしています。" % len(targets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
