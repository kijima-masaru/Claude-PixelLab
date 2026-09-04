#!/usr/bin/env python3
"""素材生成 API のクライアント。

APIキーは環境変数からのみ読む。リポジトリには一切置かない。
provider は projects/<id>/project.yaml で指定し、通信は lib/provider.py が担う。
特定サービスへ固く結合させないための境界がその2枚である。

    python tools/client.py --project iwato --kind map-object \
        --name obj_vending_machine --description "..." --dry-run

必ず守ること:
  - **上限**。--max-images と --max-cost のどちらか先に達した時点で停止する
  - **参照画像を送らない**。送信直前に lib/guard.py が検査し、違反なら止める
  - **全呼び出しをログに残す**。採否は後から postprocess/validate で更新する
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config, genlog, guard, provider  # noqa: E402

#: 生成の種類と、対応するエンドポイント。
KINDS = {
    "tileset": "/create-tileset",
    "map-object": "/map-objects",
    "ui": "/generate-ui-v2",
    "image": "/create-image-pixflux",
}

#: 既定の安全弁。上限なしでは絶対に走らせない。
DEFAULT_MAX_IMAGES = 1
DEFAULT_MAX_COST_USD = 0.20


def new_run_id() -> str:
    """docs/CONVENTIONS.md の書式 YYYYMMDD-HHMMSS-xxxx で実行単位IDを作る。"""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return stamp + "-" + suffix


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="client.py",
        description=(
            "素材生成 API のクライアント。APIキーは環境変数から読む。"
            "--dry-run では API を呼ばず、送信予定の内容のみを表示する。"
        ),
    )
    config.add_project_arg(parser)
    parser.add_argument("--kind", default="map-object", choices=sorted(KINDS),
                        help="生成の種類（既定: map-object）。")
    parser.add_argument("--name", required=True,
                        help="素材ID（例: obj_vending_machine）。出力ファイル名になる。")
    parser.add_argument("--description", help="プロンプト全文。tileset 以外で必須。")
    parser.add_argument("--lower", help="tileset: 下側の地形の説明。")
    parser.add_argument("--upper", help="tileset: 上側の地形の説明。")
    parser.add_argument("--transition", help="tileset: 境界の地形の説明。")
    parser.add_argument("--negative-prompt", default="", help="ネガティブプロンプト全文。")
    parser.add_argument("--size", type=int, default=64, metavar="PX",
                        help="出力の一辺（既定: 64）。tileset では tile_size を使う。")
    parser.add_argument("--view", default="high top-down",
                        choices=["low top-down", "high top-down", "side"],
                        help="視点（既定: high top-down）。本作は真上見下ろし。")
    parser.add_argument("--seed", type=int,
                        help="シード。同じ値で同じ結果が得られるかは実測で確認すること。"
                             "省略時は API 側が決めるため、再現できなくなる。")
    parser.add_argument("--param", action="append", default=[], metavar="KEY=VALUE",
                        help="追加パラメータ。複数指定可。全てログに記録される。")
    parser.add_argument("--run-id", help="実行単位ID。省略時は生成する。_work/<run_id>/ に対応。")
    parser.add_argument("--max-images", type=int, default=DEFAULT_MAX_IMAGES, metavar="N",
                        help="この実行で生成してよい枚数の上限（既定: %d）。" % DEFAULT_MAX_IMAGES)
    parser.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST_USD, metavar="USD",
                        help="この実行で使ってよい実額の上限（既定: $%.2f）。" % DEFAULT_MAX_COST_USD)
    parser.add_argument("--dry-run", action="store_true",
                        help="API を呼ばず、送信予定のリクエスト内容を表示して終了する。")
    return parser


def parse_params(pairs: list) -> dict:
    """KEY=VALUE の並びを dict に変換する。数値は数値として解釈する。"""
    params = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit("--param は KEY=VALUE の形式で指定してください: " + pair)
        key, value = pair.split("=", 1)
        value = value.strip()
        if value.lower() in ("true", "false"):
            params[key.strip()] = value.lower() == "true"
        else:
            try:
                params[key.strip()] = int(value)
            except ValueError:
                try:
                    params[key.strip()] = float(value)
                except ValueError:
                    params[key.strip()] = value
    return params


def build_request(cfg: dict, args: argparse.Namespace) -> tuple:
    """(エンドポイント, 送信するリクエスト) を組み立てる。APIキーは含めない。

    ここで組み立てた内容がそのまま生成ログの記録対象になる。
    """
    canvas = cfg["canvas"]
    tile = canvas["tile_size"]
    extra = parse_params(args.param)
    defaults = cfg["generation"].get("default_params") or {}
    endpoint = KINDS[args.kind]

    if args.kind == "tileset":
        if not (args.lower and args.upper):
            raise SystemExit("--kind tileset には --lower と --upper が必要です。")
        request = {
            "lower_description": args.lower,
            "upper_description": args.upper,
            "tile_size": {"width": tile, "height": tile},
            "view": args.view,
        }
        if args.transition:
            request["transition_description"] = args.transition
    elif args.kind == "ui":
        if not args.description:
            raise SystemExit("--description は必須です。")
        request = {
            "description": args.description,
            "image_size": {"width": args.size, "height": args.size},
            "no_background": True,
        }
    else:
        if not args.description:
            raise SystemExit("--description は必須です。")
        request = {
            "description": args.description,
            "image_size": {"width": args.size, "height": args.size},
        }
        if args.kind == "map-object":
            request["view"] = args.view
        else:
            request["transparent_background"] = True
        if args.negative_prompt:
            request["negative_description"] = args.negative_prompt

    if args.seed is not None and args.kind in ("tileset", "map-object"):
        request["seed"] = args.seed

    request.update(defaults)
    request.update(extra)
    return endpoint, request


def _log_record(cfg: dict, args: argparse.Namespace, endpoint: str, request: dict,
                run_id: str, output_path, usd: float, adopted, reason: str) -> dict:
    """1件分のログレコードを組み立てる。APIキーは含めない。"""
    return {
        "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "project_id": cfg["id"],
        "run_id": run_id,
        "provider": cfg["generation"]["provider"],
        "model": cfg["generation"].get("model") or endpoint,
        "model_version": None,
        "prompt": request.get("description")
        or " / ".join(filter(None, [request.get("lower_description"),
                                    request.get("upper_description"),
                                    request.get("transition_description")])),
        "negative_prompt": args.negative_prompt or request.get("negative_description") or "",
        "params": request,
        "seed": request.get("seed"),
        "seed_note": ("指定なし。API 側が決めるため引き直しても同一にならない"
                      if request.get("seed") is None else ""),
        "endpoint": endpoint,
        "asset_name": args.name,
        "output_path": str(output_path) if output_path else None,
        "asset_path": None,
        "adopted": adopted,
        "reject_reason": reason,
        "estimated_cost": usd,
        "cost_source": "usage.usd（実額）" if usd else "未取得",
    }


def strip_images(node):
    """レスポンスから base64 の塊を取り除いた写しを返す（保存・観察用）。"""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key == "base64" and isinstance(value, str):
                out[key] = "<base64 %d bytes 省略>" % len(value)
            else:
                out[key] = strip_images(value)
        return out
    if isinstance(node, list):
        return [strip_images(v) for v in node]
    if isinstance(node, str) and node.startswith("data:image/"):
        return "<data URI %d bytes 省略>" % len(node)
    return node


def response_model(body: dict) -> tuple:
    """レスポンスからモデル名とバージョンを拾う。無ければ (None, None)。

    PixelLab は応答にモデル名を返さないことがある。その場合は
    エンドポイントを model として記録し、実値が取れないことを明示する。
    """
    name = version = None

    def walk(node):
        nonlocal name, version
        if isinstance(node, dict):
            for key, value in node.items():
                lowered = str(key).lower()
                if lowered in ("model", "model_name", "model_id") and isinstance(value, str):
                    name = name or value
                elif lowered in ("model_version", "version") and isinstance(value, (str, int)):
                    version = version or str(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(body)
    return name, version


def generate(cfg: dict, endpoint: str, request: dict, args: argparse.Namespace,
             run_id: str) -> int:
    """API を呼び、中間生成物を _work/<run_id>/ に保存してログへ記録する。"""
    work = config.work_dir(cfg["id"], run_id)
    work.mkdir(parents=True, exist_ok=True)

    print(guard.describe_guard())
    print("送信します: " + endpoint)
    print("  上限: 枚数 " + str(args.max_images) + " / 実額 $" + ("%.2f" % args.max_cost))

    body, used = provider.call(endpoint, request, cfg["generation"]["provider"])
    usd = used["usd"]
    generations = used["generations"]
    images = provider.extract_images(body)

    if usd > args.max_cost:
        print("  警告: 1回の呼び出しで実額上限を超えました（$%.4f > $%.2f）" % (usd, args.max_cost))

    saved = []
    for index, blob in enumerate(images, start=1):
        if len(saved) >= args.max_images:
            print("  枚数上限 " + str(args.max_images) + " に達したため、以降は保存しません")
            break
        path = work / ("%s_%02d.png" % (args.name, index))
        path.write_bytes(blob)
        saved.append(path)

    # レスポンスの写し（画像は除く）を残す。モデル名やコストの出所を後から追える。
    meta_path = work / "response.json"
    meta_path.write_text(
        json.dumps(strip_images(body), ensure_ascii=False, indent=2),
        encoding="utf-8", newline="\n",
    )

    model_name, model_version = response_model(body)
    record = _log_record(cfg, args, endpoint, request, run_id,
                         saved[0] if saved else None, usd, None, "")
    record["model"] = model_name or cfg["generation"].get("model") or endpoint
    record["model_version"] = model_version
    record["model_source"] = "レスポンス" if model_name else "エンドポイント名で代用（応答に無し）"
    record["output_count"] = len(images)
    record["saved_count"] = len(saved)
    record["generations_used"] = generations
    record["cost_source"] = ("usage.usd（実額）" if usd
                             else ("billing_usage.generations（回数制）" if generations
                                   else "未取得"))
    log_path = genlog.append(record)

    print("")
    print("完了しました")
    print("  取得枚数 : " + str(len(images)) + "（保存 " + str(len(saved)) + "）")
    print("  保存先   : " + str(work.relative_to(config.ROOT)))
    for path in saved:
        print("    " + path.name)
    print("  モデル   : " + str(record["model"]) + "（出所: " + record["model_source"] + "）")
    print("  使用量   : $%.4f / %.1f 生成回数（出所: %s）"
          % (usd, generations, record["cost_source"]))
    print("  応答控え : " + str(meta_path.relative_to(config.ROOT)))
    print("  ログ     : " + str(log_path.relative_to(config.ROOT)))
    print("  run_id   : " + run_id)
    print("")
    print("次: python tools/postprocess.py --project " + cfg["id"] +
          " --input _work/" + run_id + " --category <category>")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load_project(args.project)
    endpoint, request = build_request(cfg, args)
    run_id = args.run_id or new_run_id()

    # 送信するしないに関わらず、必ずガードを通す。
    # --dry-run でも検査することで、事故を実行前に見つけられる。
    guard.assert_safe_request(request, where=endpoint)

    if args.dry_run:
        import os
        env_name = config.PROVIDER_ENV[cfg["generation"]["provider"]]
        key_state = "設定あり" if os.environ.get(env_name) else "未設定"
        print("[dry-run] API は呼びません。")
        print("  プロジェクト : " + config.describe(cfg))
        print("  " + guard.describe_guard() + " → 検査を通過しました")
        print("  APIキー      : 環境変数 " + env_name + " → " + key_state + "（値は表示しません）")
        print("  上限         : 枚数 " + str(args.max_images) +
              " / 実額 $" + ("%.2f" % args.max_cost))
        print("  エンドポイント: " + endpoint)
        print("  run_id       : " + run_id)
        print("  作業ディレクトリ: " + str(config.work_dir(args.project, run_id)))
        print("  送信予定のリクエスト:")
        print(json.dumps(request, ensure_ascii=False, indent=2))
        return 0

    return generate(cfg, endpoint, request, args, run_id)


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
