#!/usr/bin/env python3
"""生成ログに記録した条件で、同じ素材を **引き直す**。

    python tools/regenerate.py --project iwato --run-id 20260904-143052-a1b2 --dry-run

**重要 — これは「復元」ツールではない。**

PixelLab API には seed パラメータが存在する。しかし**実測の結果、
同一シード・同一パラメータで再送しても同一の画像は得られなかった**
（64x64 の同一条件2回で 37.9% の画素が相違）。
このスクリプトができるのは「当時と同じ条件でもう一度引く」ことだけである。

**再現性の唯一の担保は、完成品が Git LFS にあることである。**
_work/ の中間生成物を捨ててよいのはそのためであり、
ログから画像を復元できるからではない。

ログの役割は次の3つに変わった:
  1. 何をいくらで作ったかの記録（コスト管理）
  2. 同条件での引き直しのための条件保存 ← このスクリプトが使う
  3. 採否と不採用理由の蓄積（プロンプト改善のため）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config, genlog, guard, provider  # noqa: E402

#: 引き直しに最低限必要な項目。seed は決定論的でないため必須にしない。
REQUIRED_FOR_REPLAY = ("prompt", "params", "provider", "endpoint")

DEFAULT_MAX_IMAGES = 1
DEFAULT_MAX_COST_USD = 0.20


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="regenerate.py",
        description=(
            "生成ログに記録した条件で素材を引き直す。"
            "同一シードでも同一画像にはならないため、復元ではなく同条件での再生成である。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "注意:\n"
            "  同一画像の復元はできません。再現性の担保は完成品が Git LFS に\n"
            "  あることです。詳細は logs/README.md を参照してください。\n"
        ),
    )
    config.add_project_arg(parser)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-id", help="引き直す実行単位ID。")
    group.add_argument("--asset", help="引き直す完成品のパス（プロジェクト相対）。")
    group.add_argument("--rejected", action="store_true",
                       help="不採用（adopted=false）のレコードをまとめて引き直す。")
    parser.add_argument("--out", metavar="DIR",
                        help="出力先。省略時は _work/<run_id>-replay<N>/ に置く。")
    parser.add_argument("--max-images", type=int, default=DEFAULT_MAX_IMAGES, metavar="N",
                        help="この実行で保存してよい枚数の上限（既定: %d）。" % DEFAULT_MAX_IMAGES)
    parser.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST_USD, metavar="USD",
                        help="この実行で使ってよい実額の上限（既定: $%.2f）。" % DEFAULT_MAX_COST_USD)
    parser.add_argument("--dry-run", action="store_true",
                        help="API を呼ばず、引き直しに使う条件を表示して終了する。")
    return parser


def select_records(project_id: str, args: argparse.Namespace) -> list:
    """引き直し対象のログレコードを選ぶ。"""
    records = list(genlog.iter_records([project_id]))
    if args.run_id:
        return [r for r in records if r.get("run_id") == args.run_id]
    if args.asset:
        return [r for r in records if r.get("asset_path") == args.asset]
    return [r for r in records if r.get("adopted") is False]


def check_replayable(record: dict) -> list:
    """引き直しに必要な項目が揃っているかを調べ、欠けている項目名を返す。"""
    return [f for f in REQUIRED_FOR_REPLAY if not record.get(f)]


def replay(cfg: dict, record: dict, out_dir: Path, args: argparse.Namespace,
           spent: float) -> tuple:
    """1レコードを同条件で引き直す。(保存した枚数, 使った実額) を返す。

    **当時の project.yaml ではなく、ログに残っている params をそのまま使う。**
    設定が変わっていても当時と同じ条件で引けるようにするためである。
    """
    endpoint = record["endpoint"]
    request = record["params"]

    guard.assert_safe_request(request, where=endpoint)

    remaining = args.max_cost - spent
    if remaining <= 0:
        print("  実額上限に達したため送信しません。")
        return 0, 0.0

    body, used = provider.call(endpoint, request, record.get("provider", "pixellab"))
    usd = used["usd"]
    images = provider.extract_images(body)

    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for index, blob in enumerate(images, start=1):
        if len(saved) >= args.max_images:
            break
        path = out_dir / ("%s_%02d.png" % (record.get("asset_name") or "replay", index))
        path.write_bytes(blob)
        saved.append(path)

    new_record = dict(record)
    new_record.update({
        "run_id": out_dir.name,
        "output_path": str(saved[0]) if saved else None,
        "asset_path": None,
        "adopted": None,
        "reject_reason": "",
        "estimated_cost": usd,
        "generations_used": used["generations"],
        "replay_of": record.get("run_id"),
        "replay_note": "同条件での引き直し。seed 非対応のため元と同一の画像ではない",
    })
    new_record.pop("saved_count", None)
    new_record["saved_count"] = len(saved)
    genlog.append(new_record)

    for path in saved:
        print("    " + path.name)
    print("    使用量 $%.4f / %.1f 生成回数" % (usd, used["generations"]))
    return len(saved), usd


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load_project(args.project)

    records = select_records(args.project, args)
    if not records:
        print("該当するログレコードがありません: " + str(genlog.log_path(args.project)))
        return 1

    print("対象     : " + config.describe(cfg))
    print("レコード : " + str(len(records)) + " 件")
    print("上限     : 枚数 " + str(args.max_images) + " / 実額 $" + ("%.2f" % args.max_cost))
    print("")
    print("注意: seed 非対応のため、元と同一の画像は得られません（同条件での引き直しです）。")
    print("")

    blocked = 0
    for record in records:
        missing = check_replayable(record)
        run_id = record.get("run_id", "(run_id なし)")
        if missing:
            blocked += 1
            print("  [引き直し不可] " + run_id + " / 欠落項目: " + ", ".join(missing))
            continue
        print("  [引き直し可能] " + run_id)
        if args.dry_run:
            print(json.dumps(
                {k: record.get(k) for k in REQUIRED_FOR_REPLAY},
                ensure_ascii=False, indent=2,
            ))

    if blocked:
        print("")
        print("警告: " + str(blocked) + " 件が引き直し不可です。"
              "記録漏れはプロンプト改善の材料を失うため、原因を調べること。")

    if args.dry_run:
        print("")
        print("[dry-run] API は呼びません。")
        return 0

    spent, produced = 0.0, 0
    for record in records:
        if check_replayable(record):
            continue
        if produced >= args.max_images:
            print("枚数上限 " + str(args.max_images) + " に達したため停止します。")
            break
        if spent >= args.max_cost:
            print("実額上限 $%.2f に達したため停止します。" % args.max_cost)
            break
        run_id = record.get("run_id", "replay")
        out_dir = Path(args.out) if args.out else config.work_dir(
            args.project, run_id + "-replay"
        )
        print("")
        print("  引き直し: " + run_id + " → " + str(out_dir.name))
        count, usd = replay(cfg, record, out_dir, args, spent)
        produced += count
        spent += usd

    print("")
    print("引き直し %d 枚 / 実額 $%.4f" % (produced, spent))
    if produced >= args.max_images or spent >= args.max_cost:
        print("上限に達したため停止しました。")
    return 0


def _run(argv=None) -> int:
    """例外を分類して、理由の読める形で停止する。失敗は握り潰さない。"""
    from lib.guard import ReferenceLeakError
    from lib.provider import (
        AuthError, InsufficientCreditsError, ProviderError, ValidationError,
    )
    try:
        return main(argv)
    except ReferenceLeakError as exc:
        print("", file=sys.stderr)
        print("送信を中止しました（参照画像ガード）", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 2
    except AuthError as exc:
        print("", file=sys.stderr)
        print("認証に失敗しました。再試行していません。", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 3
    except InsufficientCreditsError as exc:
        print("", file=sys.stderr)
        print("クレジット不足のため停止しました。再試行していません。", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 4
    except ValidationError as exc:
        print("", file=sys.stderr)
        print("パラメータが不正です。再試行しても解決しません。", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 5
    except ProviderError as exc:
        print("", file=sys.stderr)
        print("API 呼び出しに失敗しました。", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 6


if __name__ == "__main__":
    sys.exit(_run())
