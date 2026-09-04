#!/usr/bin/env python3
"""素材生成 API のクライアント。

APIキーは環境変数からのみ読む。リポジトリには一切置かない。
provider は projects/<id>/project.yaml で指定し、ここで分岐する。
特定サービスへ固く結合させないための境界がこのファイルである。

    python tools/client.py --project iwato --prompt "..." --dry-run

現状は骨格のみ。--dry-run は完全に動作し、送信予定の内容を表示する。
実送信は未実装（次ステップ）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="client.py",
        description=(
            "素材生成 API のクライアント。APIキーは環境変数から読む。"
            "--dry-run では API を呼ばず、送信予定の内容のみを表示する。"
        ),
    )
    config.add_project_arg(parser)
    parser.add_argument("--prompt", help="生成プロンプト全文。")
    parser.add_argument("--negative-prompt", default="", help="ネガティブプロンプト全文。")
    parser.add_argument("--seed", type=int, help="シード。省略時は実行時に決めて必ずログへ記録する。")
    parser.add_argument("--count", type=int, default=1, help="生成枚数（既定: 1）。")
    parser.add_argument("--param", action="append", default=[], metavar="KEY=VALUE",
                        help="追加パラメータ。複数指定可。全てログに記録される。")
    parser.add_argument("--run-id", help="実行単位ID。省略時は生成する。_work/<run_id>/ に対応。")
    parser.add_argument("--dry-run", action="store_true",
                        help="API を呼ばず、送信予定のリクエスト内容を表示して終了する。")
    return parser


def resolve_api_key(provider: str, required: bool = True) -> str | None:
    """provider に対応する環境変数から APIキーを読む。

    値は返すだけで、表示もログ出力も一切しない。
    """
    env_name = config.PROVIDER_ENV.get(provider)
    if env_name is None:
        raise SystemExit("未知の provider: " + repr(provider))
    key = os.environ.get(env_name)
    if not key and required:
        raise SystemExit(
            "環境変数 " + env_name + " が設定されていません。\n"
            "設定方法は .env.example を参照してください。値をリポジトリに置かないこと。"
        )
    return key


def parse_params(pairs: list) -> dict:
    """KEY=VALUE の並びを dict に変換する。"""
    params = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit("--param は KEY=VALUE の形式で指定してください: " + pair)
        key, value = pair.split("=", 1)
        params[key.strip()] = value.strip()
    return params


def build_request(cfg: dict, args: argparse.Namespace) -> dict:
    """送信するリクエストを組み立てる。APIキーは含めない。

    ここで組み立てた内容がそのまま生成ログの記録対象になる。
    再現性はこの内容とシードで担保する。
    """
    canvas = cfg["canvas"]
    request = {
        "provider": cfg["generation"]["provider"],
        "model": cfg["generation"].get("model"),
        "prompt": args.prompt,
        "negative_prompt": args.negative_prompt,
        "seed": args.seed,
        "count": args.count,
        "params": {
            "tile_size": canvas["tile_size"],
            "width": canvas["base_resolution"]["width"],
            "height": canvas["base_resolution"]["height"],
            "max_colors": cfg["palette"]["max_colors"],
            **(cfg["generation"].get("default_params") or {}),
            **parse_params(args.param),
        },
    }
    return request


def generate(cfg: dict, request: dict, run_id: str) -> list:
    """実際に API を呼んで中間生成物を _work/<run_id>/ に保存する。

    未実装（次ステップ）。実装時は以下を必ず守ること:
      - 保存先は config.work_dir(project_id, run_id) 配下のみ
      - 1枚ごとに genlog.append() で記録する（採否は後から更新）
      - シード・プロンプト全文・全パラメータ・モデル名を必ず残す
      - APIキーはログにもエラーメッセージにも出さない
    """
    raise NotImplementedError(
        "API 送信は未実装です（次ステップ）。--dry-run を使ってください。"
    )


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load_project(args.project)
    provider = cfg["generation"]["provider"]

    if not args.prompt:
        raise SystemExit("--prompt は必須です。")

    request = build_request(cfg, args)
    run_id = args.run_id or "<実行時に生成>"

    if args.dry_run:
        env_name = config.PROVIDER_ENV[provider]
        key_state = "設定あり" if os.environ.get(env_name) else "未設定"
        print("[dry-run] API は呼びません。")
        print("  プロジェクト : " + config.describe(cfg))
        print("  APIキー      : 環境変数 " + env_name + " → " + key_state + "（値は表示しません）")
        print("  作業ディレクトリ: " + str(config.work_dir(args.project, args.run_id)))
        print("  送信予定のリクエスト:")
        print(json.dumps(request, ensure_ascii=False, indent=2))
        return 0

    resolve_api_key(provider)
    generate(cfg, request, run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
