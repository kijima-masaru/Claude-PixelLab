#!/usr/bin/env python3
"""パレット定義（ランプ）から .gpl とスウォッチ表を生成し、置換テーブルを検証する。

    python tools/build_palette.py --project iwato
    python tools/build_palette.py --project iwato --verify-only

色を直接並べるのではなく、系統ごとの「ランプ（明度段の列）」から生成する。
**時間帯差分をパレット置換で作る方針のため、置換が段のシフトとして
成立する構造でなければならない。** 個別に色を選ぶと、置換先がパレット内に
存在しない事態が起きる。

検証項目:
  - 総色数が max_colors ちょうどか
  - 重複した色が無いか（1色でも重複すれば実質的に色数が減る）
  - 各時間帯の置換先が全てパレット内に存在するか
  - 置換で潰れる（複数色が同じ色に写る）箇所がどれだけあるか
  - 隣接段の明度差が 32px で識別できるか
"""

from __future__ import annotations

import argparse
import colorsys
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402

try:
    import yaml
except ImportError:
    sys.exit("PyYAML が必要です: python -m pip install -r requirements.txt")

#: 隣接段として識別させたい最小の明度差（0-100 スケール）。
#: これを下回ると 32px では段が潰れて見える。
MIN_STEP_DELTA = 3.0


def hsl_to_hex(h: float, s: float, l: float) -> tuple:
    """HSL（h:0-360, s:0-1, l:0-100）を (r, g, b) に変換する。"""
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360.0, l / 100.0, s)
    return tuple(int(round(v * 255)) for v in (r, g, b))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_hue(a: float, b: float, t: float) -> float:
    """色相を**最短弧**で補間する。

    単純な線形補間だと、例えば 356 度から 34 度へ向かうときに
    色相環を逆回りして緑（150度付近）を通過してしまう。
    土のランプの中間段が緑になる、といった事故を防ぐ。
    """
    delta = (b - a) % 360.0
    if delta > 180.0:
        delta -= 360.0
    return (a + delta * t) % 360.0


def build_ramp(spec: dict) -> list:
    """1系統のランプを生成する。暗い側から明るい側へ並ぶ。"""
    n = spec["count"]
    gamma = spec.get("gamma", 1.0)
    out = []
    for i in range(n):
        t = i / (n - 1) if n > 1 else 0.0
        tl = t ** gamma
        h = lerp_hue(spec["hue"]["start"], spec["hue"]["end"], t)
        s = lerp(spec["sat"]["start"], spec["sat"]["end"], t)
        l = lerp(spec["light"]["start"], spec["light"]["end"], tl)
        out.append({
            "ramp": spec["key"], "index": i, "label": spec["label"],
            "h": h, "s": s, "l": l, "rgb": hsl_to_hex(h, s, l),
            "kind": "ground",
        })
    return out


def build_palette(spec: dict) -> list:
    colours = []
    for ramp in spec["ramps"]:
        colours.extend(build_ramp(ramp))
    for group in spec.get("light_sources", []):
        for i, c in enumerate(group["colors"]):
            colours.append({
                "ramp": group["key"], "index": i, "label": group["label"],
                "h": c["h"], "s": c["s"], "l": c["l"],
                "rgb": hsl_to_hex(c["h"], c["s"], c["l"]),
                "kind": "light",
            })
    reserve = spec.get("reserve") or {}
    for i in range(reserve.get("count", 0)):
        c = reserve["placeholder"]
        colours.append({
            "ramp": "reserve", "index": i, "label": "予備",
            "h": c["h"], "s": c["s"], "l": c["l"],
            "rgb": hsl_to_hex(c["h"], c["s"], c["l"]),
            "kind": "reserve",
        })
    return colours


def hexstr(rgb: tuple) -> str:
    return "#%02X%02X%02X" % rgb


# --- 置換テーブル -----------------------------------------------------------

def resolve(colour: dict, rules: dict, ramps: dict):
    """1色を、ある時間帯の置換規則で写す。写像先の色を返す。

    光源色と予備は置換しない（光源は時間帯で色が変わらないため）。
    """
    if colour["kind"] != "ground":
        return colour
    rule = rules.get(colour["ramp"])
    if not rule:
        return colour
    target_ramp = rule.get("to", colour["ramp"])
    shift = rule.get("shift", 0)
    n = len(ramps[target_ramp])
    index = colour["index"] + shift
    index = max(0, min(n - 1, index))   # 端で丸める
    return ramps[target_ramp][index]


def verify(colours: list, spec: dict) -> tuple:
    """パレットと置換テーブルを検証する。(問題のリスト, 統計) を返す。"""
    problems, notes = [], []
    ramps: dict = {}
    for c in colours:
        ramps.setdefault(c["ramp"], []).append(c)
    for key in ramps:
        ramps[key].sort(key=lambda c: c["index"])

    # 総色数
    total = len(colours)
    want = spec["max_colors"]
    if total != want:
        problems.append("総色数が %d です。%d ちょうどにしてください。" % (total, want))
    notes.append("総色数: %d / %d" % (total, want))

    # 重複
    seen: dict = {}
    for c in colours:
        key = c["rgb"]
        if key in seen:
            problems.append(
                "色が重複しています: %s（%s[%d] と %s[%d]）"
                % (hexstr(key), seen[key]["ramp"], seen[key]["index"], c["ramp"], c["index"])
            )
        seen[key] = c
    notes.append("ユニークな色: %d" % len(seen))

    # 隣接段の明度差
    tight = []
    for key, ramp in ramps.items():
        if key == "reserve" or ramp[0]["kind"] != "ground":
            continue
        for a, b in zip(ramp, ramp[1:]):
            d = b["l"] - a["l"]
            if d < MIN_STEP_DELTA:
                tight.append("%s[%d→%d] 明度差 %.1f" % (key, a["index"], b["index"], d))
    if tight:
        problems.append(
            "隣接段の明度差が %.1f 未満で、32px では潰れて見えます: %s"
            % (MIN_STEP_DELTA, " / ".join(tight))
        )

    # 置換テーブル
    stats = {}
    for name, variant in spec["time_variants"].items():
        rules = variant.get("rules") or {}
        for ramp_key in rules:
            if ramp_key not in ramps:
                problems.append("置換規則が存在しない系統を指しています: %s.%s" % (name, ramp_key))
            to = rules[ramp_key].get("to")
            if to and to not in ramps:
                problems.append("置換先の系統がありません: %s.%s.to=%s" % (name, ramp_key, to))

        ground = [c for c in colours if c["kind"] == "ground"]
        mapped = [resolve(c, rules, ramps) for c in ground]
        distinct = len({m["rgb"] for m in mapped})
        collapsed = len(ground) - distinct
        stats[name] = {
            "label": variant.get("label", name),
            "ground": len(ground),
            "distinct": distinct,
            "collapsed": collapsed,
            "ratio": distinct / len(ground),
        }
    return problems, (stats, ramps)


# --- 出力 -------------------------------------------------------------------

def write_gpl(colours: list, spec: dict, path: Path) -> None:
    lines = ["GIMP Palette", "Name: " + spec["name"], "Columns: 8",
             "# 磐戸町奇譚 64色パレット",
             "# 生成: python tools/build_palette.py --project iwato",
             "# 定義: projects/iwato/palettes/palette_spec.yaml",
             "#"]
    for c in colours:
        r, g, b = c["rgb"]
        lines.append("%3d %3d %3d\t%s %s%d"
                     % (r, g, b, c["ramp"], c["label"], c["index"] + 1))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def swatch_table(colours: list) -> str:
    """スウォッチ表（HEX 併記）を Markdown で返す。"""
    out, current = [], None
    for c in colours:
        if c["ramp"] != current:
            current = c["ramp"]
            out.append("")
            out.append("#### `%s` — %s" % (c["ramp"], c["label"]))
            out.append("")
            out.append("| 段 | HEX | RGB | H | S | L |")
            out.append("| ---: | --- | --- | ---: | ---: | ---: |")
        hx = hexstr(c["rgb"])
        out.append("| %d | `%s` | %d, %d, %d | %.0f | %.2f | %.0f |"
                   % (c["index"] + 1, hx,
                      c["rgb"][0], c["rgb"][1], c["rgb"][2], c["h"], c["s"], c["l"]))
    return "\n".join(out)


def substitution_table(colours: list, spec: dict, ramps: dict) -> str:
    """時間帯置換の検証結果を Markdown で返す。"""
    out = ["| 系統 | 昼（基準） | 朝 | 夕 | 夜 |", "| --- | --- | --- | --- | --- |"]
    order = ["morning", "dusk", "night"]
    for ramp in spec["ramps"]:
        key = ramp["key"]
        row = ["`%s` %s" % (key, ramp["label"])]
        base = ramps[key]
        row.append("%d段 %s→%s" % (len(base), hexstr(base[0]["rgb"]), hexstr(base[-1]["rgb"])))
        for name in order:
            rules = spec["time_variants"][name].get("rules") or {}
            mapped = [resolve(c, rules, ramps) for c in base]
            distinct = len({m["rgb"] for m in mapped})
            to = (rules.get(key) or {}).get("to", key)
            shift = (rules.get(key) or {}).get("shift", 0)
            mark = "" if distinct == len(base) else " ⚠%d潰れ" % (len(base) - distinct)
            row.append("→`%s` %+d%s" % (to, shift, mark))
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def write_swatch_sheet(colours: list, spec: dict, ramps: dict, path) -> None:
    """スウォッチ画像を書き出す。4時間帯を並べ、置換の効きを目で確認できるようにする。

    外部サービスの画像に依存させないため、リポジトリに同梱する。
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return

    order = [r["key"] for r in spec["ramps"]] + [g["key"] for g in spec["light_sources"]]
    cell, pad, label_w = 26, 2, 130
    variants = list(spec["time_variants"].items())
    longest = max(len(ramps[k]) for k in order)
    width = label_w + longest * (cell + pad) + 16
    block = len(order) * (cell + pad) + 26
    img = Image.new("RGB", (width, block * len(variants) + 12), (26, 26, 30))
    draw = ImageDraw.Draw(img)

    for vi, (vkey, _variant) in enumerate(variants):
        rules = spec["time_variants"][vkey].get("rules") or {}
        top = vi * block + 8
        # PIL の既定フォントは CJK を含まないため、画像内は ASCII のみを描く
        draw.text((8, top), vkey.upper(), fill=(228, 228, 232))
        for ri, key in enumerate(order):
            y = top + 18 + ri * (cell + pad)
            draw.text((8, y + 7), key, fill=(168, 168, 174))
            for c in ramps[key]:
                m = resolve(c, rules, ramps)
                x = label_w + c["index"] * (cell + pad)
                draw.rectangle([x, y, x + cell, y + cell], fill=m["rgb"])
    img.save(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_palette.py",
        description="palette_spec.yaml からパレットを生成し、時間帯置換テーブルを検証する。",
    )
    config.add_project_arg(parser)
    parser.add_argument("--verify-only", action="store_true",
                        help="ファイルを書かず、検証結果だけを表示する。")
    parser.add_argument("--emit-swatches", action="store_true",
                        help="スウォッチ表と置換表を標準出力に出す（PALETTE.md 用）。")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load_project(args.project)
    pal_dir = config.project_dir(args.project) / "palettes"
    spec_path = pal_dir / "palette_spec.yaml"
    if not spec_path.is_file():
        raise SystemExit("パレット定義がありません: " + str(spec_path))

    with spec_path.open(encoding="utf-8") as fh:
        spec = yaml.safe_load(fh)

    if spec["max_colors"] != cfg["palette"]["max_colors"]:
        raise SystemExit(
            "max_colors が project.yaml と一致しません: %d / %d"
            % (spec["max_colors"], cfg["palette"]["max_colors"])
        )

    colours = build_palette(spec)
    problems, (stats, ramps) = verify(colours, spec)

    if args.emit_swatches:
        print(swatch_table(colours))
        print("")
        print(substitution_table(colours, spec, ramps))
        return 0

    print("パレット定義: " + str(spec_path.relative_to(config.ROOT)))
    print("系統: %d / 光源: %d / 予備: %d"
          % (len(spec["ramps"]), sum(len(g["colors"]) for g in spec["light_sources"]),
             (spec.get("reserve") or {}).get("count", 0)))
    print("総色数: %d" % len(colours))
    print("")
    print("=== 時間帯置換の検証 ===")
    print("%-8s %-6s %8s %8s %8s" % ("時間帯", "名称", "地の色数", "識別色数", "潰れ"))
    for name, s in stats.items():
        print("%-8s %-6s %8d %8d %8d%s"
              % (name, s["label"], s["ground"], s["distinct"], s["collapsed"],
                 "" if s["collapsed"] == 0 else "  ← 情報が失われる"))
    print("")

    if problems:
        for p in problems:
            print("[問題] " + p)
        print("")
        print("失敗: %d 件の問題があります。" % len(problems))
        return 1

    print("検証: 問題なし")

    if args.verify_only:
        return 0

    gpl = pal_dir / (spec["name"] + ".gpl")
    write_gpl(colours, spec, gpl)
    print("書き出し: " + str(gpl.relative_to(config.ROOT)))

    sheet = pal_dir / (spec["name"] + "_swatches.png")
    write_swatch_sheet(colours, spec, ramps, sheet)
    if sheet.is_file():
        print("書き出し: " + str(sheet.relative_to(config.ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
