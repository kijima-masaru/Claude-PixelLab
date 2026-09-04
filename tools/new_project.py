#!/usr/bin/env python3
"""templates/project/ の雛形から新規プロジェクトを生成する。

    python tools/new_project.py --id iwato --title "磐戸町奇譚" \
        --tile-size 32 --resolution 640x360 --colors 64 \
        --engine godot --engine-version 4.7 --normalmap

生成されるもの:
  projects/<id>/project.yaml         このプロジェクトの唯一の設定元
  projects/<id>/style/               スタイルガイドとベースプロンプト
  projects/<id>/palettes/            パレット（中身は次ステップ）
  projects/<id>/requirements/        素材要件（中身は次ステップ）
  projects/<id>/assets/<category>/   完成品。LFS 管理
  projects/<id>/refs/                参考画像。Git 追跡外・ローカルのみ
  projects/<id>/_work/               中間生成物。Git 追跡外・ローカルのみ
  logs/generation_log.<id>.jsonl     このプロジェクトの生成ログ（空で作成）
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config, genlog  # noqa: E402

TEMPLATE_SUFFIX = ".tmpl"
PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")

DEFAULT_CATEGORIES = ["tilesets", "objects", "overhead", "ui", "icons"]


def parse_resolution(value: str) -> tuple[int, int]:
    """WIDTHxHEIGHT 形式を (width, height) に変換する。"""
    match = re.fullmatch(r"\s*(\d+)\s*[xX]\s*(\d+)\s*", value)
    if not match:
        raise argparse.ArgumentTypeError(
            "解像度は WIDTHxHEIGHT の形式で指定してください（例: 640x360）: " + repr(value)
        )
    return int(match.group(1)), int(match.group(2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="new_project.py",
        description="雛形から新規プロジェクトのディレクトリと設定ファイルを生成する。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            "  python tools/new_project.py --id iwato --title 磐戸町奇譚 "
            "--tile-size 32 --resolution 640x360 --colors 64 "
            "--engine godot --engine-version 4.7 --normalmap\n"
        ),
    )
    parser.add_argument("--id", required=True, metavar="PROJECT_ID",
                        help="プロジェクトID。小文字英数とハイフンのみ。ディレクトリ名になる。")
    parser.add_argument("--title", required=True,
                        help="作品タイトル（表示用。日本語可）。")
    parser.add_argument("--description", default="",
                        help="作品の一行説明（ジャンル・視点など）。")
    parser.add_argument("--engine", default="godot",
                        help="ゲームエンジン名（既定: godot）。")
    parser.add_argument("--engine-version", default="4.7",
                        help="エンジンのバージョン（既定: 4.7）。")
    parser.add_argument("--tile-size", type=int, required=True, metavar="PX",
                        help="タイル1辺のピクセル数（例: 32）。")
    parser.add_argument("--resolution", type=parse_resolution, required=True, metavar="WxH",
                        help="基準解像度（例: 640x360）。")
    parser.add_argument("--colors", type=int, required=True, metavar="N",
                        help="色数の上限（例: 64）。")
    parser.add_argument("--categories", nargs="+", default=DEFAULT_CATEGORIES, metavar="NAME",
                        help="assets/ 直下のカテゴリ（既定: " + " ".join(DEFAULT_CATEGORIES) + "）。")
    parser.add_argument("--provider", default="pixellab",
                        choices=sorted(config.PROVIDER_ENV),
                        help="生成サービス識別子（既定: pixellab）。")
    parser.add_argument("--normalmap", action="store_true",
                        help="ノーマルマップを併せて生成する構成にする。")
    parser.add_argument("--force", action="store_true",
                        help="既存のプロジェクトディレクトリを上書きする。")
    parser.add_argument("--dry-run", action="store_true",
                        help="作成せず、作られるパスの一覧だけを表示する。")
    return parser


def build_substitutions(args: argparse.Namespace) -> dict:
    """雛形の置換値を組み立てる。"""
    width, height = args.resolution
    created = dt.date.today().isoformat()
    categories = list(dict.fromkeys(args.categories))
    return {
        "id": args.id,
        "title": args.title,
        "description": args.description or "（記入する）",
        "engine_name": args.engine,
        "engine_version": args.engine_version,
        "tile_size": str(args.tile_size),
        "width": str(width),
        "height": str(height),
        "max_colors": str(args.colors),
        "palette_file": "null",
        "format": "png",
        "filter": "nearest",
        "mipmaps": "false",
        "compression": "none",
        "normalmap": "true" if args.normalmap else "false",
        "asset_categories": "[" + ", ".join(categories) + "]",
        "provider": args.provider,
        "created": created,
        "progress_rows": "\n".join("| " + c + " | - | 0 | |" for c in categories),
        "prompt_rows": "\n".join("| " + c + " | （記入する） |" for c in categories),
    }


def render(text: str, subs: dict, source: str) -> str:
    """雛形中のプレースホルダを置換する。未定義のキーがあればエラーにする。"""
    missing = []

    def replace(match):
        key = match.group(1)
        if key not in subs:
            missing.append(key)
            return match.group(0)
        return subs[key]

    rendered = PLACEHOLDER_RE.sub(replace, text)
    if missing:
        raise SystemExit(source + ": 未定義のプレースホルダ: " + ", ".join(sorted(set(missing))))
    return rendered


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config.validate_project_id(args.id)
    except config.ConfigError as exc:
        raise SystemExit(str(exc))

    if not config.TEMPLATES_DIR.is_dir():
        raise SystemExit("雛形が見つかりません: " + str(config.TEMPLATES_DIR))

    dest = config.project_dir(args.id)
    if dest.exists() and not args.force:
        raise SystemExit(
            "既に存在します: " + str(dest) + "\n上書きするなら --force を付けてください。"
        )

    subs = build_substitutions(args)
    categories = list(dict.fromkeys(c.strip() for c in args.categories))
    created = []

    # 1. 雛形のファイルを展開する（refs/ と _work/ は下で明示生成するので除く）
    for src in sorted(config.TEMPLATES_DIR.rglob("*")):
        rel = src.relative_to(config.TEMPLATES_DIR)
        if rel.parts and rel.parts[0] in config.LOCAL_ONLY_DIRS:
            continue
        target = dest / rel
        if src.is_dir():
            created.append(target)
            if not args.dry_run:
                target.mkdir(parents=True, exist_ok=True)
            continue
        if src.name.endswith(TEMPLATE_SUFFIX):
            target = target.with_name(src.name[: -len(TEMPLATE_SUFFIX)])
            created.append(target)
            if not args.dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                text = render(src.read_text(encoding="utf-8"), subs, str(src))
                target.write_text(text, encoding="utf-8", newline="\n")
        else:
            created.append(target)
            if not args.dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, target)

    # 2. assets/ のカテゴリ別ディレクトリ
    for category in categories:
        target = config.assets_dir(args.id) / category
        created.append(target / ".gitkeep")
        if not args.dry_run:
            target.mkdir(parents=True, exist_ok=True)
            (target / ".gitkeep").touch()

    # 3. Git 追跡外のディレクトリ（refs/ と _work/）
    #    .gitignore で全階層除外しているため、雛形からコピーしても追跡されず
    #    クローン直後には存在しない。ゆえにここで明示的に作る。
    #    これが無いと初回生成時にディレクトリ不在で落ちる。
    for name in config.LOCAL_ONLY_DIRS:
        target = dest / name
        created.append(target / ".gitkeep")
        if not args.dry_run:
            target.mkdir(parents=True, exist_ok=True)
            (target / ".gitkeep").touch()

    # 4. このプロジェクトの生成ログ（空ファイル）
    log_file = genlog.log_path(args.id)
    created.append(log_file)
    if not args.dry_run:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        if not log_file.exists():
            log_file.touch()

    if args.dry_run:
        print("[dry-run] 作成予定 (" + str(len(created)) + " 件):")
        for path in created:
            print("  " + str(path.relative_to(config.ROOT)))
        return 0

    # 5. 生成した設定を読み直して検証する（雛形の破損をここで検出する）
    cfg = config.load_project(args.id)

    print("作成しました: " + str(dest.relative_to(config.ROOT)))
    print("  " + config.describe(cfg))
    print("  ログ: " + str(log_file.relative_to(config.ROOT)))
    print("  Git 追跡外: " + ", ".join(name + "/" for name in config.LOCAL_ONLY_DIRS))
    print("次にやること: docs/ADDING_PROJECT.md の「作成後にやること」を参照。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
