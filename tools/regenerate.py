#!/usr/bin/env python3
"""生成ログのシードとプロンプトから、中間生成物を再生成する。

    python tools/regenerate.py --project iwato --run-id 20260904-143052-a1b2 --dry-run

このスクリプトが「中間生成物を Git に残さない」方針の担保である。
_work/ を消してもログさえ残っていれば同じものを作り直せる、という前提が
成り立たなくなった時点で方針そのものが崩れる。ゆえにログの記録項目
（シード・プロンプト全文・全パラメータ・モデル名・モデルバージョン）は
欠かしてはならない。

現状はインターフェースのみ。ログの読み出しと再現内容の表示までは動作し、
実際の再送信は未実装（次ステップ）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config, genlog  # noqa: E402

#: 再生成に最低限必要な項目。欠けていれば再現できない。
REQUIRED_FOR_REPLAY = ("prompt", "seed", "params", "model", "provider")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="regenerate.py",
        description=(
            "生成ログに記録されたシードとプロンプトから中間生成物を再生成する。"
            "_work/ を削除した後の復元手段。"
        ),
    )
    config.add_project_arg(parser)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-id", help="再生成する実行単位ID。")
    group.add_argument("--asset", help="再生成する完成品のパス（プロジェクト相対）。")
    group.add_argument("--rejected", action="store_true",
                       help="不採用（adopted=false）のレコードをまとめて再生成する。")
    parser.add_argument("--out", metavar="DIR",
                        help="出力先。省略時は _work/<run_id>/ に戻す。")
    parser.add_argument("--dry-run", action="store_true",
                        help="API を呼ばず、再現に使うログの内容を表示して終了する。")
    return parser


def select_records(project_id: str, args: argparse.Namespace) -> list:
    """再生成対象のログレコードを選ぶ。"""
    records = list(genlog.iter_records([project_id]))
    if args.run_id:
        return [r for r in records if r.get("run_id") == args.run_id]
    if args.asset:
        return [r for r in records if r.get("asset_path") == args.asset]
    return [r for r in records if r.get("adopted") is False]


def check_replayable(record: dict) -> list:
    """再現に必要な項目が揃っているかを調べ、欠けている項目名を返す。"""
    return [f for f in REQUIRED_FOR_REPLAY if record.get(f) in (None, "")]


def replay(cfg: dict, record: dict, out_dir: Path):
    """1レコードを再送信して中間生成物を復元する。

    未実装（次ステップ）。実装時は client.generate() を再利用し、
    ログに記録された値（現在の project.yaml ではなく当時の params）を
    そのまま使うこと。設定が変わっていても当時の出力を再現できるようにする。
    """
    raise NotImplementedError("再送信は未実装です（次ステップ）。")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load_project(args.project)

    records = select_records(args.project, args)
    if not records:
        print("該当するログレコードがありません: " + str(genlog.log_path(args.project)))
        return 1

    print("対象     : " + config.describe(cfg))
    print("レコード : " + str(len(records)) + " 件")

    blocked = 0
    for record in records:
        missing = check_replayable(record)
        run_id = record.get("run_id", "(run_id なし)")
        if missing:
            blocked += 1
            print("  [再現不可] " + run_id + " / 欠落項目: " + ", ".join(missing))
            continue
        out_dir = Path(args.out) if args.out else config.work_dir(args.project, run_id)
        print("  [再現可能] " + run_id + " → " + str(out_dir))
        if args.dry_run:
            print(json.dumps(
                {k: record.get(k) for k in REQUIRED_FOR_REPLAY},
                ensure_ascii=False, indent=2,
            ))

    if blocked:
        print("警告: " + str(blocked) + " 件が再現不可です。"
              "記録漏れは中間生成物を捨てる方針の前提を壊すため、原因を調べること。")

    if args.dry_run:
        print("[dry-run] API は呼びません。")
        return 0

    raise SystemExit("再生成の実装は未実装です（次ステップ）。--dry-run を使ってください。")


if __name__ == "__main__":
    sys.exit(main())
