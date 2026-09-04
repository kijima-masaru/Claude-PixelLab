#!/usr/bin/env python3
"""完成品からノーマルマップを生成する。

    python tools/normalmap.py --project iwato --category backgrounds

出力は元素材と同じディレクトリに <name>_n.png として置く（命名規則は
docs/CONVENTIONS.md を参照）。Godot の CanvasTexture が期待する接尾辞に合わせている。

現状はインターフェースのみ。生成処理は未実装（次ステップ）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402

NORMALMAP_SUFFIX = "_n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="normalmap.py",
        description="完成品からノーマルマップ（<name>_n.png）を生成する。",
    )
    config.add_project_arg(parser)
    parser.add_argument("--category", "-c", help="対象カテゴリ。省略時は全カテゴリ。")
    parser.add_argument("--path", help="単一ファイルを対象にする（プロジェクト相対）。")
    parser.add_argument("--strength", type=float, default=1.0,
                        help="凹凸の強さ（既定: 1.0）。")
    parser.add_argument("--method", default="sobel", choices=["sobel", "height"],
                        help="生成方式（既定: sobel）。")
    parser.add_argument("--overwrite", action="store_true", help="既存のノーマルマップを上書きする。")
    parser.add_argument("--dry-run", action="store_true",
                        help="書き込まず、対象と出力先だけを表示する。")
    return parser


def generate_normalmap(path: Path, strength: float, method: str):
    """1枚の素材からノーマルマップを生成して返す。

    未実装（次ステップ）。ドット絵の輪郭を保つため、生成後も
    tile_size のグリッドを崩さないこと。
    """
    raise NotImplementedError("generate_normalmap は未実装です（次ステップ）。")


def normalmap_path(source: Path) -> Path:
    """元素材のパスから、ノーマルマップの出力パスを返す。"""
    return source.with_name(source.stem + NORMALMAP_SUFFIX + source.suffix)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load_project(args.project)

    if not cfg["output"].get("normalmap"):
        print("注意: project.yaml の output.normalmap が false です。"
              "このプロジェクトはノーマルマップを使わない設定になっています。")

    categories = [args.category] if args.category else list(cfg["asset_categories"])
    print("対象     : " + config.describe(cfg))
    print("カテゴリ : " + ", ".join(categories))
    print("方式     : " + args.method + " / 強さ " + str(args.strength))
    print("出力名   : <name>" + NORMALMAP_SUFFIX + ".png")

    if args.dry_run:
        print("[dry-run] 書き込みは行いません。")
        return 0

    raise SystemExit("ノーマルマップ生成は未実装です（次ステップ）。--dry-run を使ってください。")


if __name__ == "__main__":
    sys.exit(main())
