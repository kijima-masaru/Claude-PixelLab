#!/usr/bin/env python3
"""中間生成物を完成品に仕上げる後処理。

    python tools/postprocess.py --project iwato --input _work/<run_id> --category tilesets

入力は projects/<id>/_work/ 配下の生出力、出力は projects/<id>/assets/<category>/。
パレット・タイルサイズ・色数は project.yaml から読む。ツールに直接書かない。

処理の順序には理由がある:
  1. 余白トリム          … 生出力の周囲の透明部分を落とす
  2. アンチエイリアス除去 … アルファ二値化 + パレット吸着
  3. グリッド整列        … tile_size の倍数に整える（余白は透明で足す）
最後に整列するのは、トリム前に整列しても余白の分だけずれるためである。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config, imageops  # noqa: E402


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
    parser.add_argument("--grid-mode", default="pad", choices=["pad", "crop"],
                        help="グリッド整列の方式（既定: pad = 透明で切り上げ）。")
    parser.add_argument("--skip-palette", action="store_true", help="パレット適用を行わない。")
    parser.add_argument("--skip-align", action="store_true", help="グリッド整列を行わない。")
    parser.add_argument("--skip-deaa", action="store_true", help="アンチエイリアス除去を行わない。")
    parser.add_argument("--skip-trim", action="store_true", help="余白トリムを行わない。")
    parser.add_argument("--overwrite", action="store_true", help="既存の完成品を上書きする。")
    parser.add_argument("--dry-run", action="store_true",
                        help="書き込まず、行う処理と出力先だけを表示する。")
    return parser


def resolve_palette(cfg: dict) -> tuple:
    """project.yaml の palette.file を解決する。(パレット, 表示用の説明) を返す。"""
    rel = cfg["palette"].get("file")
    if not rel:
        return None, "未設定（max_colors=%d への減色のみ）" % cfg["palette"]["max_colors"]
    path = config.project_dir(cfg["id"]) / rel
    if not path.is_file():
        raise SystemExit(
            "パレットファイルが見つかりません: " + str(path) + "\n"
            "project.yaml の palette.file を確認してください。"
        )
    palette = imageops.load_palette(path)
    if not palette:
        raise SystemExit("パレットを読み取れませんでした: " + str(path))
    return palette, str(rel) + "（" + str(len(palette)) + "色）"


def collect_inputs(base: Path) -> list:
    if base.is_file():
        return [base]
    if base.is_dir():
        return sorted(p for p in base.rglob("*.png") if p.is_file())
    raise SystemExit("入力が見つかりません: " + str(base))


def apply_palette(image, palette_path, max_colors: int):
    """パレットに量子化する。ディザリングは既定で無効。"""
    palette = imageops.load_palette(Path(palette_path)) if palette_path else None
    return imageops.apply_palette(image, palette, max_colors)


def align_to_grid(image, tile_size: int, mode: str = "pad"):
    """タイル境界にスナップし、寸法を tile_size の倍数に整える。"""
    return imageops.align_to_grid(image, tile_size, mode=mode)


def remove_antialias(image, palette, max_colors: int):
    """中間色として生じたアンチエイリアス画素を除去する。"""
    return imageops.remove_antialias(image, palette, max_colors)


def process_one(path: Path, cfg: dict, palette, args: argparse.Namespace):
    """1枚を後処理して Image を返す。"""
    image = imageops.load_rgba(path)
    tile = cfg["canvas"]["tile_size"]
    max_colors = cfg["palette"]["max_colors"]

    if not args.skip_trim:
        image = imageops.trim_transparent(image)
    if not args.skip_deaa:
        image = imageops.remove_antialias(image, palette, max_colors)
    elif not args.skip_palette:
        image = imageops.apply_palette(image, palette, max_colors)
    if not args.skip_align:
        image = imageops.align_to_grid(image, tile, mode=args.grid_mode)
    return image


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load_project(args.project)

    if args.category not in cfg["asset_categories"]:
        raise SystemExit(
            "未知のカテゴリ: " + args.category + " / 既知: " + ", ".join(cfg["asset_categories"])
        )

    palette, palette_label = resolve_palette(cfg)
    src = config.project_dir(args.project) / args.input
    dst_dir = config.assets_dir(args.project) / args.category
    inputs = collect_inputs(src)

    steps = []
    if not args.skip_trim:
        steps.append("余白トリム")
    if not args.skip_deaa:
        steps.append("アンチエイリアス除去（アルファ二値化+パレット吸着）")
    elif not args.skip_palette:
        steps.append("パレット適用")
    if not args.skip_align:
        steps.append("グリッド整列（%dpx / %s）" % (cfg["canvas"]["tile_size"], args.grid_mode))

    print("入力    : " + str(src.relative_to(config.ROOT)) + "（" + str(len(inputs)) + " 枚）")
    print("出力    : " + str(dst_dir.relative_to(config.ROOT)))
    print("パレット: " + palette_label)
    print("処理    : " + (" → ".join(steps) if steps else "（なし）"))
    print("")

    if args.dry_run:
        for path in inputs:
            print("  [dry-run] " + path.name + " → " + (args.name or path.stem) + ".png")
        print("")
        print("[dry-run] 書き込みは行いません。")
        return 0

    written = 0
    for index, path in enumerate(inputs, start=1):
        image = process_one(path, cfg, palette, args)
        stem = args.name or path.stem
        if len(inputs) > 1 and args.name:
            stem = "%s_%02d" % (args.name, index)
        out = dst_dir / (stem + ".png")
        if out.exists() and not args.overwrite:
            print("  スキップ（既存）: " + out.name + " / 上書きは --overwrite")
            continue
        imageops.save_png(image, out)
        colors = len(imageops.count_colors(image))
        written += 1
        print("  %s → %s  %dx%d  %d色" % (path.name, out.name, image.width, image.height, colors))

    print("")
    print("完成品 " + str(written) + " 枚を書き出しました。")
    print("次: python tools/validate_assets.py --project " + args.project +
          " --category " + args.category)
    return 0


if __name__ == "__main__":
    sys.exit(main())
