"""参考画像を API へ送らせないためのガード。

projects/<id>/refs/ には第三者の著作物（既存商用ゲームのスクリーンショット、
実写写真）が置かれる。これらを生成 API の入力にすると、出力が派生物と
見なされるリスクがある。したがって**いかなる形でも送信しない。**

この方針は人間の注意力に頼らず、コードで担保する。
送信直前に assert_safe_request() を通し、違反があれば例外で送信を止める。

三層で検査する:

  1. 参照画像系のパラメータ名そのものを禁止する
     本プロジェクトは reference_image / style_image / init_image /
     concept_image / inpainting_image / context_image を一切使わない。
     使わないものが載っている時点で事故なので、中身を見ずに落とす。

  2. リクエスト中の文字列に refs/ 配下のパスが現れたら落とす
     ファイルパスを渡す経路での混入を止める。

  3. base64 で埋め込まれた画像を検査する
     - refs/ のファイルとバイト列が一致するもの（ハッシュ照合）
     - JPEG のもの（本パイプラインの中間生成物・完成品は PNG のみ。
       refs/ は JPEG。JPEG が載っている時点で出所が refs/ である疑いが濃い）
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from pathlib import Path

from . import config

#: 本プロジェクトが一切使わない参照画像系パラメータ。名前の存在自体を禁止する。
FORBIDDEN_PARAMS = frozenset({
    "reference_image",
    "reference_images",
    "style_image",
    "style_images",
    "init_image",
    "concept_image",
    "inpainting_image",
    "context_image",
    "from_image",
    "portrait",
    "portrait_image",
    # 実仕様を直接確認して判明した分（/map-objects, /create-tileset）
    "background_image",
    "lower_reference_image",
    "upper_reference_image",
    "transition_reference_image",
})

#: 将来ここを緩める予定の注記。
#: 「承認済みの自作タイルのみを参照画像に使う」手順に入る段階で、
#: 名前による一律禁止から「自作素材のみ許可」へ切り替える。
#: そのときも refs/ のパス照合・ハッシュ照合・JPEG 検出は残すこと。

#: 自作画像を正当に送る可能性があるパラメータ（後処理系）。中身を検査する。
CONTENT_CHECKED_PARAMS = frozenset({
    "image", "images", "mask_image", "palette_image",
    "frames", "edit_images", "first_frame", "start_image", "end_image",
})

#: base64 らしき文字列の判定。データURI の前置きも許す。
_DATA_URI_RE = re.compile(r"^data:image/[a-zA-Z0-9.+-]+;base64,", re.IGNORECASE)
_B64_RE = re.compile(r"^[A-Za-z0-9+/\r\n]{64,}={0,2}$")

#: マジックナンバー
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class ReferenceLeakError(Exception):
    """参考画像を送信しようとしたことを表す。握り潰さず必ず送信を止める。"""


def _refs_dirs() -> list[Path]:
    """リポジトリ内の refs/ ディレクトリを全て返す。"""
    found = []
    if config.PROJECTS_DIR.is_dir():
        for project in config.PROJECTS_DIR.iterdir():
            candidate = project / "refs"
            if candidate.is_dir():
                found.append(candidate.resolve())
    template_refs = config.TEMPLATES_DIR / "refs"
    if template_refs.is_dir():
        found.append(template_refs.resolve())
    return found


def refs_hashes() -> dict:
    """refs/ 配下の全ファイルの SHA-256 を返す。{hash: 表示用パス}"""
    digests = {}
    for directory in _refs_dirs():
        for path in directory.rglob("*"):
            if not path.is_file() or path.name == ".gitkeep":
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            try:
                label = str(path.relative_to(config.ROOT))
            except ValueError:
                label = str(path)
            digests[digest] = label
    return digests


def _mentions_refs_path(text: str) -> bool:
    """文字列が refs/ 配下を指しているか。"""
    normalised = text.replace("\\", "/")
    if "/refs/" in normalised or normalised.startswith("refs/"):
        return True
    return False


def _decode_base64(value: str) -> bytes | None:
    """base64 らしき文字列をデコードする。画像でなければ None。"""
    payload = value
    match = _DATA_URI_RE.match(value)
    if match:
        payload = value[match.end():]
    elif not _B64_RE.match(value.strip()):
        return None
    try:
        raw = base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError):
        return None
    if raw.startswith(_JPEG_MAGIC) or raw.startswith(_PNG_MAGIC):
        return raw
    return None


def assert_safe_request(request, where: str = "request", _known: dict | None = None) -> None:
    """送信直前のリクエストを検査する。違反があれば ReferenceLeakError。

    request は dict / list / str のいずれでもよく、再帰的に検査する。
    """
    known = refs_hashes() if _known is None else _known

    if isinstance(request, dict):
        for key, value in request.items():
            path = where + "." + str(key)
            if key in FORBIDDEN_PARAMS:
                raise ReferenceLeakError(
                    "参照画像パラメータは使用禁止です: " + path + "\n"
                    "本プロジェクトは refs/ の第三者著作物を API に送らない方針であり、"
                    "参照画像系のパラメータ自体を使いません。\n"
                    "画風の固定は、承認済みの自作タイルを使う手順で行ってください。"
                )
            assert_safe_request(value, path, known)
        return

    if isinstance(request, (list, tuple)):
        for index, value in enumerate(request):
            assert_safe_request(value, where + "[" + str(index) + "]", known)
        return

    if not isinstance(request, str):
        return

    if _mentions_refs_path(request):
        raise ReferenceLeakError(
            "refs/ 配下のパスを API に渡そうとしています: " + where + "\n"
            "値: " + request[:120] + "\n"
            "refs/ には第三者の著作物が置かれます。送信しないでください。"
        )

    raw = _decode_base64(request)
    if raw is None:
        return

    digest = hashlib.sha256(raw).hexdigest()
    if digest in known:
        raise ReferenceLeakError(
            "参考画像そのものを base64 で送ろうとしています: " + where + "\n"
            "一致したファイル: " + known[digest] + "\n"
            "refs/ の画像は API に送らないでください。"
        )

    if raw.startswith(_JPEG_MAGIC):
        raise ReferenceLeakError(
            "JPEG 画像を送ろうとしています: " + where + "\n"
            "本パイプラインが扱う画像は PNG のみです（中間生成物も完成品も PNG）。"
            "JPEG は refs/ の参考画像である可能性が高いため、送信を止めました。"
        )


def describe_guard() -> str:
    """ガードの現在の監視対象を1行で返す（ログ・表示用）。"""
    known = refs_hashes()
    return (
        "参照画像ガード: 禁止パラメータ " + str(len(FORBIDDEN_PARAMS)) + " 種 / "
        "refs/ の監視対象 " + str(len(known)) + " ファイル"
    )
