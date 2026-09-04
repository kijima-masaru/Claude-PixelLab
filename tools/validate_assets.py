#!/usr/bin/env python3
"""完成品が品質基準を満たしているかを検査する。

    python tools/validate_assets.py --project iwato
    python tools/validate_assets.py --project iwato --category tilesets

検査基準は projects/<id>/project.yaml から読む。基準の定義は
docs/CONVENTIONS.md の「素材の品質基準」を参照。

現状はインターフェースのみ。各検査は未実装（次ステップ）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402

CHECKS = ("palette", "grid", "alpha")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate_assets.py",
        description="完成品のパレット適合・グリッド・透明度を検査する。",
    )
    config.add_project_arg(parser)
    parser.add_argument("--category", "-c", help="検査対象カテゴリ。省略時は全カテゴリ。")
    parser.add_argument("--path", help="単一ファイル／ディレクトリを検査する（プロジェクト相対）。")
    parser.add_argument("--check", nargs="+", choices=CHECKS, default=list(CHECKS),
                        metavar="NAME", help="実行する検査（既定: " + " ".join(CHECKS) + "）。")
    parser.add_argument("--strict", action="store_true",
                        help="警告も失敗として扱う（CI 用）。")
    return parser


def check_palette(path: Path, palette_path, max_colors: int) -> list:
    """使用色がパレット内かつ max_colors 以下かを検査する。

    未実装（次ステップ）。違反があれば違反内容の一覧を返す設計にする。
    """
    raise NotImplementedError("check_palette は未実装です（次ステップ）。")


def check_grid(path: Path, tile_size: int) -> list:
    """寸法が tile_size の倍数か、タイル境界がずれていないかを検査する。

    未実装（次ステップ）。
    """
    raise NotImplementedError("check_grid は未実装です（次ステップ）。")


def check_alpha(path: Path) -> list:
    """半透明画素の有無を検査する（透明は 0 か 255 のみを許容する）。

    未実装（次ステップ）。
    """
    raise NotImplementedError("check_alpha は未実装です（次ステップ）。")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load_project(args.project)

    categories = [args.category] if args.category else list(cfg["asset_categories"])
    unknown = [c for c in categories if c not in cfg["asset_categories"]]
    if unknown:
        raise SystemExit(
            "未知のカテゴリ: " + ", ".join(unknown) + " / 既知: " + ", ".join(cfg["asset_categories"])
        )

    print("対象      : " + config.describe(cfg))
    print("カテゴリ  : " + ", ".join(categories))
    print("実行検査  : " + ", ".join(args.check))
    print("判定基準  : パレット<=" + str(cfg["palette"]["max_colors"]) + "色 / "
          "グリッド" + str(cfg["canvas"]["tile_size"]) + "px / 半透明画素なし")

    raise SystemExit("検査の実装は未実装です（次ステップ）。")


if __name__ == "__main__":
    sys.exit(main())
