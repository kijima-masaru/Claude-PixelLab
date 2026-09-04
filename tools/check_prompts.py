#!/usr/bin/env python3
"""base.yaml のプロンプトが、そのまま送信できる状態かを検証する。

    python tools/check_prompts.py --project iwato

**API は呼ばない。** 各 asset のリクエストを組み立て、
参照画像ガードを通し、必須項目が揃っているかを確認するだけである。

生成枠が限られている状況で、壊れたプロンプトに枠を使わないための検査。
プロンプトを直したら必ずこれを通してから送信すること。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import client  # noqa: E402
from lib import config, guard  # noqa: E402

try:
    import yaml
except ImportError:
    sys.exit("PyYAML が必要です: python -m pip install -r requirements.txt")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_prompts.py",
        description="base.yaml の各プロンプトを組み立て、送信可能かを検証する。API は呼ばない。",
    )
    config.add_project_arg(parser)
    parser.add_argument("--show", action="store_true",
                        help="組み立てたリクエストの中身も表示する。")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load_project(args.project)
    path = config.project_dir(args.project) / "style" / "prompts" / "base.yaml"
    if not path.is_file():
        raise SystemExit("プロンプト定義がありません: " + str(path))

    with path.open(encoding="utf-8") as fh:
        spec = yaml.safe_load(fh)

    controls = spec.get("style_controls") or {}
    prefix = (spec.get("common_prefix") or "").strip()
    suffix = (spec.get("common_suffix") or "").strip()
    pilot = spec.get("pilot") or {}
    assets = pilot.get("assets") or []

    print("プロンプト定義: " + str(path.relative_to(config.ROOT)))
    print("パイロット対象: %d 点" % len(assets))
    print("共通の画風パラメータ: " + ", ".join(
        "%s=%s" % (k, v) for k, v in controls.items() if k != "color_image"))
    print("パレット強制: " + str(controls.get("color_image") or "（なし）"))
    print("")

    problems = []
    total_lo = total_hi = 0

    for asset in sorted(assets, key=lambda a: a.get("order", 0)):
        aid = asset["id"]
        kind = "tileset" if asset["endpoint"] == "/create-tileset" else "map-object"
        # use_common_affix: false の素材は共通接辞を付けない。
        # タイルセットで判明した「共通文が素材の語を希釈する」問題への対応。
        pre = "" if asset.get("use_common_affix") is False else prefix
        suf = "" if asset.get("use_common_affix") is False else suffix

        # client.py と同じ経路でリクエストを組み立てる
        argv_ = ["--project", args.project, "--kind", kind, "--name", aid,
                 "--guidance", str(controls.get("text_guidance_scale", 8.0)),
                 "--outline", controls.get("outline", "lineless"),
                 "--shading", controls.get("shading", "basic shading"),
                 "--detail", asset.get("detail") or controls.get("detail", "low detail"),
                 "--dry-run"]
        if controls.get("color_image"):
            argv_ += ["--color-image", controls["color_image"]]
        if kind == "tileset":
            argv_ += ["--lower", " ".join(x for x in [pre, asset["lower_description"], suf] if x),
                      "--upper", " ".join(x for x in [pre, asset["upper_description"], suf] if x)]
            if asset.get("transition_description"):
                argv_ += ["--transition", asset["transition_description"]]
        else:
            size = (asset.get("params") or {}).get("image_size") or {}
            argv_ += ["--description", " ".join(x for x in [pre, asset["description"], suf] if x),
                      "--size", str(size.get("width", 64)),
                      "--view", controls.get("view", "high top-down")]

        try:
            parsed = client.build_parser().parse_args(argv_)
            endpoint, request = client.build_request(cfg, parsed)
            guard.assert_safe_request(request, where=endpoint)
        except SystemExit as exc:
            problems.append("%s: リクエストを組み立てられません: %s" % (aid, exc))
            continue
        except guard.ReferenceLeakError as exc:
            problems.append("%s: 参照画像ガードに抵触: %s" % (aid, str(exc).splitlines()[0]))
            continue

        # 必須項目の確認
        if kind == "tileset":
            missing = [k for k in ("lower_description", "upper_description", "tile_size")
                       if not request.get(k)]
        else:
            missing = [k for k in ("description", "image_size") if not request.get(k)]
        if missing:
            problems.append("%s: 必須項目が欠けています: %s" % (aid, ", ".join(missing)))

        if "color_image" not in request:
            problems.append("%s: color_image が載っていません。"
                            "negative が使えないため、これが無いと配色を抑えられません。" % aid)

        cost = str(asset.get("cost_estimate_generations", "?"))
        lo, _, hi = cost.partition("〜")
        try:
            total_lo += int(lo); total_hi += int(hi or lo)
        except ValueError:
            pass

        prompt_len = len(request.get("description")
                         or request.get("lower_description", ""))
        print("[OK] %-22s %-16s %-12s prompt %3d文字  約%s gen"
              % (aid, endpoint, asset.get("verifies", "")[:10], prompt_len, cost))
        if args.show:
            print(json.dumps(client.strip_images(request), ensure_ascii=False, indent=2))

    print("")
    print("第1パスの推定消費: %d〜%d generations" % (total_lo, total_hi))
    budget = pilot.get("budget") or {}
    if budget.get("generations_available"):
        print("使える枠: %s / 床: %s" % (budget["generations_available"], budget.get("floor")))
        if total_hi > int(budget["generations_available"]):
            problems.append(
                "第1パスの上限 %d が使える枠 %s を超えています。"
                % (total_hi, budget["generations_available"])
            )
    print("")

    for p in problems:
        print("[問題] " + p)
    if problems:
        print("")
        print("失敗: %d 件" % len(problems))
        return 1
    print("検証: 問題なし。そのまま送信できます。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
