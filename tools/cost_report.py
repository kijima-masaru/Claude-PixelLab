#!/usr/bin/env python3
"""生成ログを集計してコストと採否を報告する。

    python tools/cost_report.py                      # 全プロジェクト横断
    python tools/cost_report.py --project iwato      # プロジェクト単体

ログは logs/generation_log.<project_id>.jsonl にプロジェクト別で置かれている。
横断集計は複数ファイルを読んで行う（genlog.iter_records がそれを担う）。

**コストは推定値ではなく、レスポンスの usage.usd（実額）を合計している。**
PixelLab は固定単価表を公開しておらず、GPU 処理時間で変動するため、
自前の単価表を持たない設計にしてある。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config, genlog  # noqa: E402

GROUPS = ("project", "model", "day", "endpoint", "asset")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cost_report.py",
        description="生成ログをプロジェクト別・期間別に集計する。--project 省略時は全プロジェクト横断。",
    )
    config.add_project_arg(parser, required=False)
    parser.add_argument("--since", metavar="YYYY-MM-DD", help="この日付以降のレコードのみ集計する。")
    parser.add_argument("--until", metavar="YYYY-MM-DD", help="この日付以前のレコードのみ集計する。")
    parser.add_argument("--group-by", default="project", choices=list(GROUPS),
                        help="集計単位（既定: project）。")
    parser.add_argument("--format", default="table", choices=["table", "csv", "json"],
                        help="出力形式（既定: table）。")
    return parser


def _day(record: dict) -> str:
    return str(record.get("timestamp") or "")[:10]


def in_range(record: dict, since, until) -> bool:
    day = _day(record)
    if since and day and day < since:
        return False
    if until and day and day > until:
        return False
    return True


def group_key(record: dict, group_by: str) -> str:
    if group_by == "project":
        return record.get("project_id") or "(不明)"
    if group_by == "model":
        return record.get("model") or "(不明)"
    if group_by == "day":
        return _day(record) or "(不明)"
    if group_by == "endpoint":
        return record.get("endpoint") or "(不明)"
    return record.get("asset_name") or "(不明)"


def summarize(records, group_by: str) -> dict:
    """レコード列を集計する。件数・採否・実額の合計を返す。"""
    buckets: dict = defaultdict(lambda: {
        "calls": 0, "images": 0, "adopted": 0, "rejected": 0, "undecided": 0,
        "usd": 0.0, "generations": 0.0,
    })
    for record in records:
        bucket = buckets[group_key(record, group_by)]
        bucket["calls"] += 1
        bucket["images"] += int(record.get("output_count") or 0)
        adopted = record.get("adopted")
        if adopted is True:
            bucket["adopted"] += 1
        elif adopted is False:
            bucket["rejected"] += 1
        else:
            bucket["undecided"] += 1
        for field, key in (("estimated_cost", "usd"), ("generations_used", "generations")):
            try:
                bucket[key] += float(record.get(field) or 0.0)
            except (TypeError, ValueError):
                pass
    return dict(buckets)


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

    records = [r for r in genlog.iter_records(project_ids)
               if in_range(r, args.since, args.until)]
    print("レコード数: " + str(len(records)))
    print("")
    if not records:
        print("該当期間に生成実績がありません。")
        return 0

    summary = summarize(records, args.group_by)
    total_calls = sum(b["calls"] for b in summary.values())
    total_images = sum(b["images"] for b in summary.values())
    total_usd = sum(b["usd"] for b in summary.values())
    total_gen = sum(b["generations"] for b in summary.values())

    if args.format == "json":
        print(json.dumps({"group_by": args.group_by, "summary": summary,
                          "total": {"calls": total_calls, "images": total_images,
                                    "usd": round(total_usd, 6),
                                    "generations": total_gen}},
                         ensure_ascii=False, indent=2))
        return 0

    if args.format == "csv":
        writer = csv.writer(sys.stdout, lineterminator="\n")
        writer.writerow([args.group_by, "calls", "images", "adopted", "rejected",
                         "undecided", "usd", "generations"])
        for key in sorted(summary):
            b = summary[key]
            writer.writerow([key, b["calls"], b["images"], b["adopted"],
                             b["rejected"], b["undecided"], "%.6f" % b["usd"],
                             "%.1f" % b["generations"]])
        writer.writerow(["TOTAL", total_calls, total_images, "", "", "",
                         "%.6f" % total_usd, "%.1f" % total_gen])
        return 0

    width = max([len(str(k)) for k in summary] + [len(args.group_by)])
    print("%-*s  %6s %7s %6s %6s %6s %10s %8s"
          % (width, args.group_by, "コール", "画像", "採用", "不採用", "未決",
             "実額USD", "生成回数"))
    print("-" * (width + 62))
    for key in sorted(summary):
        b = summary[key]
        print("%-*s  %6d %7d %6d %6d %6d %10.4f %8.1f"
              % (width, key, b["calls"], b["images"], b["adopted"],
                 b["rejected"], b["undecided"], b["usd"], b["generations"]))
    print("-" * (width + 62))
    print("%-*s  %6d %7d %6s %6s %6s %10.4f %8.1f"
          % (width, "合計", total_calls, total_images, "", "", "", total_usd, total_gen))
    print("")
    print("※ いずれもレスポンスの実測値の合計です。推定値ではありません。")
    print("※ 従量課金なら usage.usd、回数制なら billing_usage.generations に載ります。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
