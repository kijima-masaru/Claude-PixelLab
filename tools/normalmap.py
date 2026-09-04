#!/usr/bin/env python3
"""完成品からノーマルマップを生成する。

    python tools/normalmap.py --project iwato --category tilesets

出力は元素材と同じディレクトリに <name>_n.png として置く（命名規則は
docs/CONVENTIONS.md を参照）。Godot の CanvasTexture が期待する接尾辞に合わせている。

**API は使わない。すべてローカルで生成する。**
443点分の API コストを 0 にするための方針である。

Godot で使う際の注意、および Laigter を使う場合の手順は
docs/NORMALMAP.md にまとめてある。**Y 軸の反転が必要**である点に注意すること。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config, imageops  # noqa: E402

NORMALMAP_SUFFIX = "_n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="normalmap.py",
        description="完成品からノーマルマップ（<name>_n.png）をローカル生成する。API は使わない。",
    )
    config.add_project_arg(parser)
    parser.add_argument("--category", "-c", help="対象カテゴリ。省略時は全カテゴリ。")
    parser.add_argument("--path", help="単一ファイルを対象にする（プロジェクト相対）。")
    parser.add_argument("--strength", type=float, default=1.0,
                        help="凹凸の強さ（既定: 1.0）。")
    parser.add_argument("--method", default="sobel", choices=["sobel", "height"],
                        help="生成方式（既定: sobel）。")
    parser.add_argument("--no-flip-y", action="store_true",
                        help="Y 軸を反転しない。**Godot では反転が必要なので通常は指定しない。**")
    parser.add_argument("--overwrite", action="store_true", help="既存のノーマルマップを上書きする。")
    parser.add_argument("--dry-run", action="store_true",
                        help="書き込まず、対象と出力先だけを表示する。")
    return parser


def normalmap_path(source: Path) -> Path:
    """元素材のパスから、ノーマルマップの出力パスを返す。"""
    return source.with_name(source.stem + NORMALMAP_SUFFIX + source.suffix)


def is_normalmap(path: Path) -> bool:
    return path.stem.endswith(NORMALMAP_SUFFIX)


def generate_normalmap(path: Path, strength: float, method: str, flip_y: bool = True):
    """1枚の素材からノーマルマップを生成して返す。"""
    return imageops.generate_normalmap(
        imageops.load_rgba(path), strength=strength, method=method, flip_y=flip_y
    )


def collect_targets(cfg: dict, args: argparse.Namespace) -> list:
    project = config.project_dir(cfg["id"])
    if args.path:
        base = project / args.path
        if base.is_file():
            return [base]
        if base.is_dir():
            return sorted(p for p in base.rglob("*.png") if not is_normalmap(p))
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
            targets.extend(sorted(p for p in directory.rglob("*.png") if not is_normalmap(p)))
    return targets


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load_project(args.project)
    flip_y = not args.no_flip_y

    if not cfg["output"].get("normalmap"):
        print("注意: project.yaml の output.normalmap が false です。"
              "このプロジェクトはノーマルマップを使わない設定になっています。")

    targets = collect_targets(cfg, args)
    print("対象     : " + config.describe(cfg))
    print("方式     : " + args.method + " / 強さ " + str(args.strength))
    print("Y 軸反転 : " + ("あり（Godot 用。これが正しい）" if flip_y else "なし（--no-flip-y 指定）"))
    print("出力名   : <name>" + NORMALMAP_SUFFIX + ".png")
    print("対象枚数 : " + str(len(targets)))
    print("")

    if not targets:
        print("対象の完成品がありません。")
        return 0

    if args.dry_run:
        for path in targets:
            print("  [dry-run] " + path.name + " → " + normalmap_path(path).name)
        print("")
        print("[dry-run] 書き込みは行いません。")
        return 0

    written = 0
    for path in targets:
        out = normalmap_path(path)
        if out.exists() and not args.overwrite:
            print("  スキップ（既存）: " + out.name + " / 上書きは --overwrite")
            continue
        image = generate_normalmap(path, args.strength, args.method, flip_y=flip_y)
        imageops.save_png(image, out)
        written += 1
        print("  " + path.name + " → " + out.name + "  %dx%d" % image.size)

    print("")
    print("ノーマルマップ " + str(written) + " 枚を書き出しました。API コスト $0.00")
    print("Godot 側の設定は docs/NORMALMAP.md を参照してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
