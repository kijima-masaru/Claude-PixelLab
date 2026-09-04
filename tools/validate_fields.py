#!/usr/bin/env python3
"""フィールド定義 fields.json を検証する。

    python tools/validate_fields.py --project iwato

検査項目:
  - スキーマ適合（schema/fields.schema.json）
  - フィールドID の書式・重複・連番
  - 出口の参照先が実在すること、自己参照でないこと
  - **出口の双方向性**（A→B があれば B→A も存在すること）
  - fields.json の topology_constraints に書かれた接続制約
  - size_tiles が画面数の目安に収まっていること
  - required_tiles / required_objects / interactables の素材ID 命名規則
  - terrain_vocabulary に無い地形語が使われていないこと

接続制約はツールに書かず fields.json 側に持たせている。
プロジェクト固有の値をツールへ持ち込まないための設計である。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402

FIELDS_FILENAME = "fields.json"
SCHEMA_FILENAME = "fields.schema.json"

FIELD_ID_RE = re.compile(r"^F[0-9]{2}$")
ASSET_ID_RE = re.compile(r"^(tile|obj|ovh|ui|icon)_[a-z0-9_]+$")


class Report:
    """検査結果を貯めて、まとめて出力する。失敗を握り潰さないための入れ物。"""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def ok(self) -> bool:
        return not self.errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate_fields.py",
        description="fields.json の構造・素材ID・接続の双方向性・接続制約を検証する。",
    )
    config.add_project_arg(parser)
    parser.add_argument("--strict", action="store_true",
                        help="警告も失敗として扱う（CI 用）。")
    parser.add_argument("--quiet", action="store_true",
                        help="エラーと警告のみを出力する。")
    return parser


def fields_path(project_id: str) -> Path:
    return config.project_dir(project_id) / "requirements" / FIELDS_FILENAME


def load_fields(project_id: str) -> dict:
    path = fields_path(project_id)
    if not path.is_file():
        raise SystemExit("フィールド定義が見つかりません: " + str(path))
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def check_schema(data: dict, report: Report) -> None:
    """schema/fields.schema.json に照らして検証する。"""
    schema_path = config.ROOT / "schema" / SCHEMA_FILENAME
    if not schema_path.is_file():
        report.warn("スキーマが見つかりません: " + str(schema_path))
        return
    try:
        import jsonschema  # type: ignore
    except ImportError:
        report.note("jsonschema 未導入のためスキーマ検証は省略（他の検査は実行済み）")
        return
    with schema_path.open(encoding="utf-8") as fh:
        schema = json.load(fh)
    validator = jsonschema.Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        loc = "/".join(str(p) for p in err.absolute_path) or "(ルート)"
        report.error("スキーマ違反 " + loc + ": " + err.message)


def check_ids(fields: list, report: Report) -> None:
    seen: set[str] = set()
    for index, field in enumerate(fields, start=1):
        fid = field.get("id", "")
        if not FIELD_ID_RE.match(fid):
            report.error("フィールドID の書式が不正: " + repr(fid))
            continue
        if fid in seen:
            report.error("フィールドID が重複: " + fid)
        seen.add(fid)
        expected = "F%02d" % index
        if fid != expected:
            report.warn("フィールドID が連番ではありません: " + fid + " (期待値 " + expected + ")")


def check_exits(fields: list, report: Report) -> None:
    """出口の参照先と、双方向性を検査する。"""
    by_id = {f["id"]: f for f in fields}
    edges: set[tuple[str, str]] = set()

    for field in fields:
        fid = field["id"]
        targets: list[str] = []
        for exit_ in field.get("exits", []):
            to = exit_.get("to")
            if to == fid:
                report.error(fid + ": 自分自身への出口があります")
                continue
            if to not in by_id:
                report.error(fid + ": 存在しないフィールドへの出口: " + str(to))
                continue
            if to in targets:
                report.error(fid + ": 同じ接続先への出口が重複: " + to)
            targets.append(to)
            edges.add((fid, to))
            if exit_.get("gated") and not exit_.get("gate"):
                report.warn(fid + " -> " + to + ": gated=true ですが gate（解放条件）が未記入です")

    # 双方向性
    for src, dst in sorted(edges):
        if (dst, src) not in edges:
            report.error(
                "出口が一方通行です: " + src + " -> " + dst +
                " に対応する " + dst + " -> " + src + " がありません"
            )

    isolated = [f["id"] for f in fields if not f.get("exits")]
    for fid in isolated:
        report.error(fid + ": 出口が1つもありません")

    report.note("接続の辺数: " + str(len(edges) // 2) + "（双方向を1本として数えた場合）")


def neighbours(fields: list) -> dict:
    graph = {f["id"]: set() for f in fields}
    for field in fields:
        for exit_ in field.get("exits", []):
            to = exit_.get("to")
            if to in graph:
                graph[field["id"]].add(to)
    return graph


def reachable(graph: dict, start: str, blocked: set | None = None) -> set:
    """start から到達できるフィールドの集合。blocked は通過禁止のフィールド。"""
    blocked = blocked or set()
    if start in blocked or start not in graph:
        return set()
    seen = {start}
    stack = [start]
    while stack:
        current = stack.pop()
        for nxt in graph.get(current, ()):
            if nxt in seen or nxt in blocked:
                continue
            seen.add(nxt)
            stack.append(nxt)
    return seen


def check_constraints(data: dict, report: Report) -> None:
    """fields.json の topology_constraints を検査する。"""
    fields = data["fields"]
    by_id = {f["id"]: f for f in fields}
    graph = neighbours(fields)

    for rule in data.get("topology_constraints", []):
        kind = rule.get("type")
        reason = rule.get("reason", "")

        if kind == "exits_exactly":
            fid = rule["field"]
            expected = set(rule.get("to", []))
            actual = graph.get(fid, set())
            if actual != expected:
                report.error(
                    "制約違反 exits_exactly " + fid + ": 期待 " + str(sorted(expected)) +
                    " / 実際 " + str(sorted(actual)) + " — " + reason
                )

        elif kind == "gated_entry":
            fid = rule["field"]
            open_entries = []
            for other in fields:
                if other["id"] == fid:
                    continue
                for exit_ in other.get("exits", []):
                    if exit_.get("to") == fid and not exit_.get("gated"):
                        open_entries.append(other["id"])
            if open_entries:
                report.error(
                    "制約違反 gated_entry " + fid + ": 制限なしで進入できる経路があります " +
                    str(sorted(open_entries)) + " — " + reason
                )

        elif kind == "choke_point":
            fid, via, start = rule["field"], rule["via"], rule["from"]
            if fid in reachable(graph, start, blocked={via}):
                report.error(
                    "制約違反 choke_point: " + via + " を通らずに " + start +
                    " から " + fid + " へ到達できます — " + reason
                )

        elif kind == "all_reachable":
            start = rule["from"]
            got = reachable(graph, start)
            missing = sorted(set(by_id) - got)
            if missing:
                report.error(
                    "制約違反 all_reachable: " + start + " から到達できないフィールド " +
                    str(missing) + " — " + reason
                )

        elif kind == "boundary":
            report.note("不変条件 boundary " + rule.get("field", "") + ": " + reason)


def check_sizes(data: dict, report: Report) -> None:
    screen = data["screen_tiles"]
    per_screen = screen["w"] * screen["h"]
    guide = data.get("size_guideline_screens") or {}
    lo = guide.get("min")
    hi = guide.get("max")
    exempt = set(guide.get("exempt", []))
    tile_size = data["tile_size"]

    for field in data["fields"]:
        fid = field["id"]
        size = field["size_tiles"]
        screens = (size["w"] * size["h"]) / per_screen
        label = fid + " " + str(size["w"]) + "x" + str(size["h"]) + " タイル = " + \
            str(size["w"] * tile_size) + "x" + str(size["h"] * tile_size) + "px = " + \
            ("%.2f" % screens) + " 画面"
        report.note(label)
        if fid in exempt:
            continue
        if lo is not None and screens < lo:
            report.warn(fid + ": 面積が目安を下回ります（" + ("%.2f" % screens) + " < " + str(lo) + " 画面）")
        if hi is not None and screens > hi:
            report.warn(fid + ": 面積が目安を超えます（" + ("%.2f" % screens) + " > " + str(hi) + " 画面）")


def check_assets(data: dict, report: Report) -> None:
    """素材ID の命名規則と、地形語の統制語彙への適合を検査する。"""
    vocab = {entry["key"] for entry in data.get("terrain_vocabulary", [])}
    tile_defs: dict[str, tuple] = {}

    def check_tile_entry(fid: str, tile: dict) -> None:
        tid = tile["id"]
        if not tid.startswith("tile_"):
            report.error(fid + ": タイルセットIDは tile_ で始めること: " + tid)
        if not ASSET_ID_RE.match(tid):
            report.error(fid + ": 素材ID の書式が不正: " + tid)
        for key in ("lower", "upper", "transition"):
            value = tile.get(key)
            if value is None:
                continue
            if value not in vocab:
                report.error(
                    fid + " / " + tid + ": terrain_vocabulary に無い地形語 " + repr(value) +
                    "（" + key + "）"
                )
        signature = (tile.get("lower"), tile.get("upper"), tile.get("transition"))
        if tid in tile_defs and tile_defs[tid] != signature:
            report.error(
                "同じタイルセットID " + tid + " が異なる地形の組で定義されています: " +
                str(tile_defs[tid]) + " と " + str(signature)
            )
        tile_defs.setdefault(tid, signature)

    for field in data["fields"]:
        fid = field["id"]
        for tile in field.get("required_tiles", []):
            check_tile_entry(fid, tile)
        for asset in field.get("required_objects", []):
            if not ASSET_ID_RE.match(asset):
                report.error(fid + ": 素材ID の書式が不正: " + asset)
            if not asset.startswith(("obj_", "ovh_")):
                report.error(fid + ": required_objects は obj_ か ovh_ で始めること: " + asset)
        for item in field.get("interactables", []):
            asset = item["asset"]
            if not ASSET_ID_RE.match(asset):
                report.error(fid + ": interactables の素材ID が不正: " + asset)
            declared = set(field.get("required_objects", []))
            for sub in field.get("sub_maps", []):
                declared.update(sub.get("required_objects", []))
            if asset not in declared:
                report.warn(
                    fid + ": interactables の " + asset +
                    " が required_objects に含まれていません（発注漏れになります）"
                )
        for sub in field.get("sub_maps", []):
            for tile in sub.get("required_tiles", []):
                check_tile_entry(sub["id"], tile)
            for asset in sub.get("required_objects", []):
                if not ASSET_ID_RE.match(asset):
                    report.error(sub["id"] + ": 素材ID の書式が不正: " + asset)

    unused = sorted(vocab - {v for sig in tile_defs.values() for v in sig if v})
    if unused:
        report.warn("terrain_vocabulary に未使用の地形語があります: " + ", ".join(unused))


def check_consistency_with_project(data: dict, cfg: dict, report: Report) -> None:
    if data["tile_size"] != cfg["canvas"]["tile_size"]:
        report.error(
            "tile_size が project.yaml と一致しません: fields.json=" + str(data["tile_size"]) +
            " / project.yaml=" + str(cfg["canvas"]["tile_size"])
        )
    res = cfg["canvas"]["base_resolution"]
    expected = {"w": res["width"] / cfg["canvas"]["tile_size"],
                "h": res["height"] / cfg["canvas"]["tile_size"]}
    actual = data["screen_tiles"]
    if abs(actual["w"] - expected["w"]) > 1e-6 or abs(actual["h"] - expected["h"]) > 1e-6:
        report.error(
            "screen_tiles が基準解像度から算出した値と一致しません: " +
            str(actual) + " / 期待 " + str(expected)
        )
    if data["project_id"] != cfg["id"]:
        report.error("project_id が一致しません: " + data["project_id"] + " / " + cfg["id"])


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load_project(args.project)
    data = load_fields(args.project)
    report = Report()

    check_schema(data, report)
    check_consistency_with_project(data, cfg, report)
    check_ids(data["fields"], report)
    check_exits(data["fields"], report)
    check_constraints(data, report)
    check_sizes(data, report)
    check_assets(data, report)

    if not args.quiet:
        print("検証対象: " + str(fields_path(args.project).relative_to(config.ROOT)))
        print("フィールド数: " + str(len(data["fields"])))
        for note in report.notes:
            print("  - " + note)
        print("")

    for warning in report.warnings:
        print("[警告] " + warning)
    for error in report.errors:
        print("[エラー] " + error)

    if report.errors:
        print("")
        print("失敗: エラー " + str(len(report.errors)) + " 件 / 警告 " + str(len(report.warnings)) + " 件")
        return 1
    if report.warnings and args.strict:
        print("")
        print("失敗（--strict）: 警告 " + str(len(report.warnings)) + " 件")
        return 1
    print("")
    print("合格: エラー 0 件 / 警告 " + str(len(report.warnings)) + " 件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
