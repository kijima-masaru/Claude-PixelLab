#!/usr/bin/env python3
"""発注表に従ってオブジェクトを生成し、検査して納品する。

    python tools/make_pixellab_objects.py --project iwato --only obj_bench,obj_torii
    python tools/make_pixellab_objects.py --project iwato --all --retries 3

**タイルは手続き的生成、物は PixelLab**（PILOT_FINDINGS 第19節）。
発注表は projects/<id>/style/prompts/objects.yaml。

  - 記述は素材の語だけ。**共通接尾辞は短く保つ**（第3節）
  - **既定は地の色のみのパレット。** 光源色を渡すと光らない物まで
    鮮やかになる。自ら発光する物だけ全76色を使う
  - 1点あたり **--retries 回まで**。それで基準を満たさなければ
    **未納品として記録し、次へ進む。** 粘らない

生成後は tools/deliver_object.py と同じ基準で判定し、
合格したものだけを assets/objects/ へ置く。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402
import deliver_object  # noqa: E402
from tile_from_texture import load_palette  # noqa: E402

try:
    import yaml
except ImportError:
    sys.exit("PyYAML が必要です")
try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow が必要です")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="make_pixellab_objects.py",
        description="発注表に従ってオブジェクトを生成し、検査して納品する。")
    config.add_project_arg(parser)
    parser.add_argument("--spec", default="style/prompts/objects.yaml")
    parser.add_argument("--only", help="カンマ区切りの id。指定した点だけ作る。")
    parser.add_argument("--all", action="store_true", help="発注表の全点を作る。")
    parser.add_argument("--retries", type=int, default=3,
                        help="1点あたりの試行回数（既定: 3）。**超えたら未納品にする**。")
    parser.add_argument("--floor", type=int, default=1500,
                        help="残高の下限。**これを割ったら止める**（既定: 1500）。")
    parser.add_argument("--category", default="objects")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def balance() -> float:
    """残高を問い合わせる。**課金されない。**"""
    from lib import provider
    import urllib.request
    key = provider.resolve_api_key("pixellab")
    req = urllib.request.Request("https://api.pixellab.ai/v2/balance",
                                 headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=30) as res:
        data = json.loads(res.read().decode("utf-8"))
    sub = data.get("subscription") or {}
    return float(sub.get("generations") or 0)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load_project(args.project)
    root = config.project_dir(args.project)
    spec = yaml.safe_load((root / args.spec).read_text(encoding="utf-8"))

    wanted = None
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
    elif not args.all:
        raise SystemExit("--only か --all を指定してください")

    suffix = spec["common_suffix"].strip()
    controls = spec["style_controls"]
    luminous = set(spec.get("luminous") or [])
    palettes = spec["palettes"]

    palette = set(load_palette(root / palettes["luminous"]))
    terrain = set(load_palette(root / palettes["default"]))
    lights = palette - terrain

    work = root / "_work/pixellab_objects"
    work.mkdir(parents=True, exist_ok=True)
    dst = config.assets_dir(args.project) / args.category
    dst.mkdir(parents=True, exist_ok=True)

    todo = [o for o in spec["objects"]
            if not o.get("skip") and (wanted is None or o["id"] in wanted)]
    print("対象 %d 点 / 試行 %d 回まで / 残高の下限 %d" % (len(todo), args.retries, args.floor))

    delivered, failed = [], {}
    for index, item in enumerate(todo, 1):
        name = item["id"]
        if (dst / (name + ".png")).is_file():
            print("[済] %s" % name)
            delivered.append(name)
            continue
        left = balance()
        if left < args.floor:
            print("**残高が下限を割りました（%d）。ここで止めます。**" % left)
            break
        pal_rel = palettes["luminous"] if name in luminous else palettes["default"]
        print("[%2d/%2d] %-30s size=%-4d %s  残高%d"
              % (index, len(todo), name, item["size"],
                 "光源色あり" if name in luminous else "地の色のみ", left))
        if args.dry_run:
            continue
        best = None
        for attempt in range(1, args.retries + 1):
            argv2 = ["--project", args.project, "--kind", "map-object", "--name", name,
                     "--description", "%s, %s" % (item["desc"], suffix),
                     "--size", str(item["size"]), "--view", controls["view"],
                     "--outline", controls["outline"], "--shading", controls["shading"],
                     "--detail", controls["detail"],
                     "--guidance", str(controls["text_guidance_scale"]),
                     "--color-image", pal_rel, "--max-images", "1", "--max-cost", "0.10"]
            run = subprocess.run([sys.executable, str(Path(__file__).with_name("client.py"))] + argv2,
                                 capture_output=True, text=True, encoding="utf-8")
            out = run.stdout or ""
            run_id = next((l.split(":")[-1].strip() for l in out.splitlines() if "run_id" in l), None)
            if not run_id:
                print("      %d回目 生成に失敗: %s" % (attempt, (run.stderr or out)[-160:].strip()))
                time.sleep(1)
                continue
            produced = sorted((root / "_work" / run_id).glob("%s_*.png" % name))
            if not produced:
                print("      %d回目 画像が取れませんでした" % attempt)
                continue
            image = Image.open(produced[0])
            problems, stats = deliver_object.inspect(image, palette, lights, ground_layer=True,
                                                     luminous=name in luminous)
            note = ("色%d 光%.0f%% 細%.0f%% 明%.0f"
                    % (stats.get("colours", 0), stats.get("light_area", 0) * 100,
                       stats.get("thin_ratio", 0) * 100, stats.get("mean_light", 0)))
            if not problems:
                image.convert("RGBA").save(dst / (name + ".png"))
                shutil.copy(produced[0], work / (name + ".png"))
                print("      %d回目 **合格** %s" % (attempt, note))
                delivered.append(name)
                best = None
                break
            print("      %d回目 不合格 %s — %s" % (attempt, note, problems[0][:70]))
            best = (problems, note)
            shutil.copy(produced[0], work / ("%s_try%d.png" % (name, attempt)))
        else:
            if best:
                failed[name] = best[0]
    print("")
    print("納品 %d 点 / 未納品 %d 点" % (len(delivered), len(failed)))
    for name, problems in failed.items():
        print("  [未納品] %-30s %s" % (name, problems[0][:80]))
    (work / "result.json").write_text(
        json.dumps({"delivered": delivered, "failed": failed}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
