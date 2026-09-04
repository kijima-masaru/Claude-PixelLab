#!/usr/bin/env python3
"""fields.json の素材要件を集計し、発注リストを出力する。

    python tools/aggregate_assets.py --project iwato
    python tools/aggregate_assets.py --project iwato --format markdown

集計単位は「API の1コール」である。タイル1枚ではない。
PixelLab の /create-tileset は1コールで16タイルを返すため、
タイル単位で数えるとコストも工数も実態から外れる。

  required_tiles  -> /create-tileset      1エントリ = 1コール
  required_objects(obj_) -> /map-objects  1エントリ = 1コール
  required_objects(ovh_) -> /map-objects  1エントリ = 1コール

UI とアイコンは fields.json に持たせていない（フィールドに紐づかないため）。
それらは ASSETS_NEEDED.md 側で列挙する。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402

#: 1コールあたりの推定コスト（USD）。PixelLab は固定単価表を公開しておらず、
#: レスポンスの usage.usd が実額を返す。ここの値は発注前の規模把握にのみ使い、
#: 実績は必ず usage.usd の合計で報告すること。
UNIT_COST_USD = {
    "tileset": (0.015, 0.020),
    "map_object": (0.010, 0.020),
}

#: 採用1点あたり平均何回生成するかの見込み。1回で通ることは稀である。
ATTEMPT_FACTOR = 3


#: 生産計画の分類ごとの、1点あたりの消費 generations。
#: PILOT_FINDINGS.md の実測に基づく。
CLASS_COST = {
    "tileset_a": (3, 4),
    "tileset_b": (3, 4),
    "tileset_roof": (3, 4),
    "deco": (1, 1),
    "object_low": (1, 1),
    "object_tall": (0, 0),      # 未解決のため見積もらない
}

#: 採用1点あたりの平均試行回数。
PLAN_ATTEMPTS = 3


def load_plan(project_id: str):
    """production_plan.yaml を読む。無ければ None。"""
    try:
        import yaml
    except ImportError:
        return None
    path = config.project_dir(project_id) / "requirements" / "production_plan.yaml"
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def report_plan(project_id: str, data: dict, plan: dict, attempts: int) -> None:
    """生産計画に沿って、作り方別の点数と消費を集計する。"""
    agg = aggregate(data)
    heights = plan.get("object_heights") or {}

    tilesets = plan.get("tilesets") or {}
    roofs = plan.get("roof_tilesets") or {}
    deco = plan.get("deco") or {}

    # タイルセット本数
    n_a = sum(1 for v in tilesets.values() if v.get("class") == "tileset_a")
    n_b = sum(1 for v in tilesets.values() if v.get("class") == "tileset_b")
    n_roof = len(roofs)

    # オブジェクトを高さで仕分ける
    deco_ids = set(deco)
    replaced = {o for r in roofs.values() for o in (r.get("replaces") or [])}
    buckets = {"deco": 0, "object_low": 0, "object_tall": 0, "roof": 0}
    for asset in agg["objects"]:
        if asset in deco_ids:
            buckets["deco"] += 1
        elif asset in replaced:
            buckets["roof"] += 1
        else:
            buckets[heights.get(asset, "object_low")] =                 buckets.get(heights.get(asset, "object_low"), 0) + 1
    n_deco = buckets["deco"] + sum(1 for k in deco if k.startswith("deco_"))
    n_ovh = len(agg["overheads"])

    rows = [
        ("タイルセット A（地形ペア）", n_a, "tileset_a", "実証済み"),
        ("タイルセット B（平坦2素材）", n_b, "tileset_b", "未検証"),
        ("屋根タイルセット", n_roof, "tileset_roof", "未検証"),
        ("地面の装飾（ground_detail）", n_deco, "deco", "投影の影響なし"),
        ("低い単体物（objects）", buckets.get("object_low", 0), "object_low", "未検証"),
        ("overhead", n_ovh, "object_low", "未検証"),
        ("高い単体物（objects）", buckets.get("object_tall", 0), "object_tall", "**未解決**"),
    ]

    print("=" * 88)
    print("生産計画に沿った再集計（作り方別）")
    print("=" * 88)
    print("%-30s %6s %10s %18s  %s" % ("区分", "点数", "コール", "generations", "状態"))
    print("-" * 88)
    lo_t = hi_t = calls_t = pts_t = 0
    for label, n, cls, state in rows:
        lo, hi = CLASS_COST[cls]
        calls = n * attempts
        glo, ghi = calls * lo, calls * hi
        lo_t += glo; hi_t += ghi; calls_t += calls; pts_t += n
        cost = "未定" if cls == "object_tall" else "%d - %d" % (glo, ghi)
        print("%-30s %6d %10d %18s  %s" % (label, n, calls, cost, state))
    print("-" * 88)
    print("%-30s %6d %10d %18s" % ("小計（未解決を除く）", pts_t, calls_t, "%d - %d" % (lo_t, hi_t)))
    print("")
    print("  タイルセットから得られるタイル: %d 枚（1本16タイル）" % ((n_a + n_b + n_roof) * 16))
    print("")
    print("  ※ UI とアイコンは fields.json に含まれない。ASSETS_NEEDED.md を参照。")
    print("  ※ 高い単体物 %d 点は作り方が未解決のため見積もらない。"
          % buckets.get("object_tall", 0))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aggregate_assets.py",
        description="fields.json の required_tiles / required_objects を API のコール単位で集計する。",
    )
    config.add_project_arg(parser)
    parser.add_argument("--format", default="table", choices=["table", "markdown", "json"],
                        help="出力形式（既定: table）。")
    parser.add_argument("--plan", action="store_true",
                        help="production_plan.yaml に沿って作り方別に集計する。")
    parser.add_argument("--attempts", type=int, default=ATTEMPT_FACTOR, metavar="N",
                        help="採用1点あたりの平均生成回数の見込み（既定: %d）。" % ATTEMPT_FACTOR)
    return parser


def load_fields(project_id: str) -> dict:
    path = config.project_dir(project_id) / "requirements" / "fields.json"
    if not path.is_file():
        raise SystemExit("フィールド定義が見つかりません: " + str(path))
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def aggregate(data: dict) -> dict:
    """タイルセット・オブジェクト・オーバーヘッドを、使用フィールド付きで集計する。"""
    tilesets: dict = {}
    tileset_users: dict = defaultdict(list)
    objects: dict = defaultdict(list)
    overheads: dict = defaultdict(list)

    def absorb(scope_id: str, node: dict) -> None:
        for tile in node.get("required_tiles", []):
            tilesets.setdefault(tile["id"], tile)
            if scope_id not in tileset_users[tile["id"]]:
                tileset_users[tile["id"]].append(scope_id)
        for asset in node.get("required_objects", []):
            bucket = overheads if asset.startswith("ovh_") else objects
            if scope_id not in bucket[asset]:
                bucket[asset].append(scope_id)

    for field in data["fields"]:
        absorb(field["id"], field)
        for sub in field.get("sub_maps", []):
            absorb(sub["id"], sub)

    return {
        "tilesets": tilesets,
        "tileset_users": dict(tileset_users),
        "objects": dict(objects),
        "overheads": dict(overheads),
    }


def cost_range(count: int, kind: str, attempts: int) -> tuple:
    lo, hi = UNIT_COST_USD[kind]
    return (count * attempts * lo, count * attempts * hi)


def render_markdown(data: dict, agg: dict, attempts: int) -> str:
    vocab = {v["key"]: v for v in data["terrain_vocabulary"]}
    out: list = []

    shared = sorted(
        (tid for tid, t in agg["tilesets"].items() if len(agg["tileset_users"][tid]) >= 2),
        key=lambda t: (-len(agg["tileset_users"][t]), t),
    )
    unique = sorted(tid for tid in agg["tilesets"] if tid not in shared)

    out.append("| タイルセットID | 内容 | lower | upper | transition | 使用数 | 使用フィールド |")
    out.append("| --- | --- | --- | --- | --- | ---: | --- |")
    for tid in shared + unique:
        tile = agg["tilesets"][tid]
        users = agg["tileset_users"][tid]
        trans = tile.get("transition")
        out.append(
            "| `%s` | %s | %s | %s | %s | %d | %s |" % (
                tid, tile["label"],
                vocab.get(tile["lower"], {}).get("ja", tile["lower"]),
                vocab.get(tile["upper"], {}).get("ja", tile["upper"]),
                vocab.get(trans, {}).get("ja", trans) if trans else "—",
                len(users), ", ".join(users),
            )
        )
    out.append("")

    for title, bucket in (("objects レイヤー", agg["objects"]), ("overhead レイヤー", agg["overheads"])):
        out.append("### " + title + "（%d 点）" % len(bucket))
        out.append("")
        out.append("| 素材ID | 使用数 | 使用フィールド |")
        out.append("| --- | ---: | --- |")
        for asset, users in sorted(bucket.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            out.append("| `%s` | %d | %s |" % (asset, len(users), ", ".join(users)))
        out.append("")

    return "\n".join(out)


def render_table(data: dict, agg: dict, attempts: int) -> str:
    out: list = []
    ts, obj, ovh = agg["tilesets"], agg["objects"], agg["overheads"]
    shared_ts = [t for t in ts if len(agg["tileset_users"][t]) >= 2]

    out.append("=== タイルセット（/create-tileset のコール数） ===")
    for tid, tile in sorted(ts.items(), key=lambda kv: (-len(agg["tileset_users"][kv[0]]), kv[0])):
        users = agg["tileset_users"][tid]
        mark = "共通" if len(users) >= 2 else "固有"
        out.append("  [%s] %-22s %2d field  %s" % (mark, tid, len(users), ",".join(users)))
    out.append("")

    out.append("=== objects レイヤー（/map-objects のコール数） ===")
    for asset, users in sorted(obj.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out.append("  %-30s %2d field  %s" % (asset, len(users), ",".join(users)))
    out.append("")

    out.append("=== overhead レイヤー（/map-objects のコール数） ===")
    for asset, users in sorted(ovh.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out.append("  %-30s %2d field  %s" % (asset, len(users), ",".join(users)))
    out.append("")

    n_ts, n_obj, n_ovh = len(ts), len(obj), len(ovh)
    ts_cost = cost_range(n_ts, "tileset", attempts)
    ob_cost = cost_range(n_obj + n_ovh, "map_object", attempts)

    out.append("=== 集計 ===")
    out.append("  タイルセット      : %3d コール（うち共通 %d / 固有 %d）" % (n_ts, len(shared_ts), n_ts - len(shared_ts)))
    out.append("  objects           : %3d コール" % n_obj)
    out.append("  overhead          : %3d コール" % n_ovh)
    out.append("  ------------------------------")
    out.append("  fields.json 由来  : %3d コール" % (n_ts + n_obj + n_ovh))
    out.append("")
    out.append("  タイルから得られるタイル枚数: 約 %d 枚（1コール16タイル）" % (n_ts * 16))
    out.append("")
    out.append("  推定コスト（試行回数 x%d を見込む）" % attempts)
    out.append("    タイルセット : $%.2f - $%.2f" % ts_cost)
    out.append("    オブジェクト : $%.2f - $%.2f" % ob_cost)
    out.append("    合計         : $%.2f - $%.2f" % (ts_cost[0] + ob_cost[0], ts_cost[1] + ob_cost[1]))
    out.append("")
    out.append("  ※ UI とアイコンは fields.json に含まれない。ASSETS_NEEDED.md を参照。")
    out.append("  ※ 実額はレスポンスの usage.usd を合計して報告すること。上記は規模把握用。")
    return "\n".join(out)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config.load_project(args.project)
    data = load_fields(args.project)
    agg = aggregate(data)

    if args.plan:
        plan = load_plan(args.project)
        if not plan:
            raise SystemExit("production_plan.yaml がありません。")
        report_plan(args.project, data, plan, args.attempts)
        return 0

    if args.format == "json":
        payload = {
            "tilesets": {tid: {**tile, "used_by": agg["tileset_users"][tid]}
                         for tid, tile in agg["tilesets"].items()},
            "objects": agg["objects"],
            "overheads": agg["overheads"],
            "counts": {
                "tilesets": len(agg["tilesets"]),
                "objects": len(agg["objects"]),
                "overheads": len(agg["overheads"]),
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.format == "markdown":
        print(render_markdown(data, agg, args.attempts))
    else:
        print(render_table(data, agg, args.attempts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
