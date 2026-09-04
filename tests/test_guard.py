#!/usr/bin/env python3
"""参照画像ガードの回帰テスト。

    python tests/test_guard.py

refs/ の第三者著作物を API へ送らないという方針は、
人間の注意力ではなくコードで担保している（tools/lib/guard.py）。
その担保が実際に働くことを、ここで機械的に確かめる。

pytest には依存しない。標準の python で単体実行できる。
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from lib import config, guard  # noqa: E402

PASSED: list = []
FAILED: list = []


def expect_blocked(label: str, request, needle: str = "") -> None:
    """ガードが例外で止めることを期待する。"""
    try:
        guard.assert_safe_request(request, where="/create-map-object")
    except guard.ReferenceLeakError as exc:
        message = str(exc).replace("\n", " ")
        if needle and needle not in message:
            FAILED.append((label, "止めたが理由が想定と違う: " + message[:120]))
            return
        PASSED.append((label, message[:96]))
        return
    FAILED.append((label, "★止まらなかった★"))


def expect_allowed(label: str, request) -> None:
    """ガードが通すことを期待する。"""
    try:
        guard.assert_safe_request(request, where="/create-map-object")
    except guard.ReferenceLeakError as exc:
        FAILED.append((label, "★正当なリクエストを止めてしまった★ " + str(exc)[:120]))
        return
    PASSED.append((label, "通過"))


def a_reference_file() -> Path | None:
    """refs/ にある実ファイルを1つ返す。無ければ None。"""
    refs = config.refs_dir("iwato")
    if not refs.is_dir():
        return None
    for path in sorted(refs.iterdir()):
        if path.is_file() and path.name != ".gitkeep":
            return path
    return None


def main() -> int:
    print("参照画像ガードの発火テスト")
    print(guard.describe_guard())
    print("")

    # --- 1. 禁止パラメータ名 ---------------------------------------------
    for name in sorted(guard.FORBIDDEN_PARAMS):
        expect_blocked(
            "禁止パラメータ " + name,
            {"description": "a vending machine", name: "whatever"},
            needle="参照画像パラメータは使用禁止",
        )

    # --- 2. refs/ のパス文字列 -------------------------------------------
    expect_blocked(
        "refs/ のパス（相対）",
        {"description": "x", "image": "projects/iwato/refs/IMG_0310.jpeg"},
        needle="refs/ 配下のパス",
    )
    expect_blocked(
        "refs/ のパス（Windows 区切り）",
        {"description": "x", "image": r"projects\iwato\refs\IMG_0310.jpeg"},
        needle="refs/ 配下のパス",
    )
    expect_blocked(
        "refs/ のパスが入れ子の配列の中にある",
        {"images": [{"src": "some/dir/refs/photo.png"}]},
        needle="refs/ 配下のパス",
    )

    # --- 3. base64 で埋め込まれた参考画像そのもの -------------------------
    sample = a_reference_file()
    if sample is None:
        print("!! refs/ に参考画像が無いため、ハッシュ照合のテストは省略します")
    else:
        encoded = base64.b64encode(sample.read_bytes()).decode("ascii")
        expect_blocked(
            "参考画像そのものを base64 で送る（ハッシュ一致）",
            {"description": "x", "image": encoded},
            needle="参考画像そのものを base64",
        )
        expect_blocked(
            "同上・データURI 形式",
            {"image": "data:image/jpeg;base64," + encoded},
            needle="参考画像そのものを base64",
        )
        expect_blocked(
            "同上・深い入れ子",
            {"payload": {"frames": [{"image": {"type": "base64", "base64": encoded}}]}},
            needle="参考画像そのものを base64",
        )

    # --- 4. refs/ 由来でない JPEG も止める --------------------------------
    # 本パイプラインが扱う画像は PNG のみ。JPEG が載る時点で出所が怪しい。
    fake_jpeg = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 400).decode("ascii")
    expect_blocked(
        "refs/ 由来でない JPEG",
        {"description": "x", "image": fake_jpeg},
        needle="JPEG 画像を送ろうとしています",
    )

    # --- 5. 正当なリクエストは通す ----------------------------------------
    expect_allowed(
        "通常の生成リクエスト",
        {
            "description": "a japanese roadside vending machine, top-down",
            "image_size": {"width": 64, "height": 64},
            "view": "high top-down",
        },
    )
    expect_allowed(
        "タイルセットのリクエスト",
        {
            "lower_description": "cracked grey asphalt road surface",
            "upper_description": "sun-scorched patchy late-summer grass",
            "tile_size": {"width": 32, "height": 32},
        },
    )
    expect_allowed(
        "自作 PNG を後処理に送る（reduce-colors 相当）",
        {"images": [base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 400).decode("ascii")]},
    )
    expect_allowed(
        "'refs' を含むが別語である文字列",
        {"description": "a shelf with reference books, top-down"},
    )

    # --- 結果 -------------------------------------------------------------
    print("%-52s %s" % ("テスト項目", "結果"))
    print("-" * 100)
    for label, detail in PASSED:
        print("%-52s OK   %s" % (label, detail))
    for label, detail in FAILED:
        print("%-52s NG   %s" % (label, detail))
    print("")
    print("成功 %d / 失敗 %d" % (len(PASSED), len(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
