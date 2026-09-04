#!/usr/bin/env python3
"""生成ログを集計してコストと採否を報告する。

    python tools/cost_report.py                      # 全プロジェクト横断
    python tools/cost_report.py --project iwato      # プロジェクト単体

ログは logs/generation_log.<project_id>.jsonl にプロジェクト別で置かれている。
横断集計は複数ファイルを読んで行う（genlog.iter_records がそれを担う）。

現状は骨格のみ。集計処理は未実装（次ステップ）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config, genlog  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cost_report.py",
        description="生成ログをプロジェクト別・期間別に集計する。--project 省略時は全プロジェクト横断。",
    )
    config.add_project_arg(parser, required=False)
    parser.add_argument("--since", metavar="YYYY-MM-DD", help="この日付以降のレコードのみ集計する。")
    parser.add_argument("--until", metavar="YYYY-MM-DD", help="この日付以前のレコードのみ集計する。")
    parser.add_argument("--group-by", default="project",
                        choices=["project", "model", "day", "category"],
                        help="集計単位（既定: project）。")
    parser.add_argument("--format", default="table", choices=["table", "csv", "json"],
                        help="出力形式（既定: table）。")
    return parser


def summarize(records, group_by: str) -> dict:
    """レコード列を集計する。

    未実装（次ステップ）。件数・採用数・不採用数・推定コスト合計を出す。
    """
    raise NotImplementedError("summarize は未実装です（次ステップ）。")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    project_ids = [args.project] if args.project else None
    targets = genlog.list_log_files(project_ids)
    existing = [p for p in targets if p.is_file()]

    print("集計対象ログ (" + str(len(existing)) + " ファイル):")
    for path in existing:
        print("  " + str(path.relative_to(config.ROOT)))
    if not existing:
        print("  （なし）")
        return 0

    count = sum(1 for _ in genlog.iter_records(project_ids))
    print("レコード数: " + str(count))
    if count == 0:
        print("まだ生成実績がありません。")
        return 0

    raise SystemExit("集計の実装は未実装です（次ステップ）。")


if __name__ == "__main__":
    sys.exit(main())
