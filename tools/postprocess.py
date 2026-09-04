#!/usr/bin/env python3
"""中間生成物を完成品に仕上げる後処理。

    python tools/postprocess.py --project iwato --input _work/<run_id> --category backgrounds

入力は projects/<id>/_work/ 配下の生出力、出力は projects/<id>/assets/<category>/。
パレット・タイルサイズ・色数は project.yaml から読む。ツールに直接書かない。

現状はインターフェースのみ。各処理は未実装（次ステップ）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="postprocess.py",
        description="中間生成物にパレット適用・グリッド整列・アンチエイリアス除去を施し、完成品として出力する。",
    )
    config.add_project_arg(parser)
    parser.add_argument("--input", "-i", required=True, metavar="PATH",
                        help="入力パス。プロジェクト相対（例: _work/20260904-143052-a1b2）。")
    parser.add_argument("--category", "-c", required=True,
                        help="出力先カテゴリ。project.yaml の asset_categories のいずれか。")
    parser.add_argument("--name", help="出力ファイル名の基幹部分。省略時は入力名を引き継ぐ。")
    parser.add_argument("--skip-palette", action="store_true", help="パレット適用を行わない。")
    parser.add_argument("--skip-align", action="store_true", help="グリッド整列を行わない。")
    parser.add_argument("--skip-deaa", action="store_true", help="アンチエイリアス除去を行わない。")
    parser.add_argument("--dry-run", action="store_true",
                        help="書き込まず、行う処理と出力先だけを表示する。")
    return parser


def apply_palette(image, palette_path: Path, max_colors: int):
    """パレットに量子化する。色数は max_colors 以下に収める。

    未実装（次ステップ）。ディザリングは既定で無効にすること。
    """
    raise NotImplementedError("apply_palette は未実装です（次ステップ）。")


def align_to_grid(image, tile_size: int):
    """タイル境界にスナップし、寸法を tile_size の倍数に整える。

    未実装（次ステップ）。
    """
    raise NotImplementedError("align_to_grid は未実装です（次ステップ）。")


def remove_antialias(image, max_colors: int):
    """中間色として生じたアンチエイリアス画素を除去する。

    未実装（次ステップ）。半透明画素の扱いは docs/CONVENTIONS.md の品質基準に従う。
    """
    raise NotImplementedError("remove_antialias は未実装です（次ステップ）。")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load_project(args.project)

    if args.category not in cfg["asset_categories"]:
        raise SystemExit(
            "未知のカテゴリ: " + args.category + " / 既知: " + ", ".join(cfg["asset_categories"])
        )

    src = config.project_dir(args.project) / args.input
    dst = config.assets_dir(args.project) / args.category
    steps = []
    if not args.skip_deaa:
        steps.append("アンチエイリアス除去")
    if not args.skip_palette:
        steps.append("パレット適用（<=" + str(cfg["palette"]["max_colors"]) + "色）")
    if not args.skip_align:
        steps.append("グリッド整列（" + str(cfg["canvas"]["tile_size"]) + "px）")

    print("入力  : " + str(src))
    print("出力  : " + str(dst))
    print("処理  : " + (" → ".join(steps) if steps else "（なし）"))

    if args.dry_run:
        print("[dry-run] 書き込みは行いません。")
        return 0

    raise SystemExit("後処理の実装は未実装です（次ステップ）。--dry-run を使ってください。")


if __name__ == "__main__":
    sys.exit(main())
