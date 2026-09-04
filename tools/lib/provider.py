"""生成サービスとの通信層。

client.py と regenerate.py の両方から使う。
特定サービスへの結合をここ1枚に閉じ込め、provider を切り替えれば
他サービスへ移れる形にしてある。

守っていること:
  - APIキーは環境変数からのみ読む。戻り値にもログにも例外文にも出さない
  - 送信直前に guard.assert_safe_request() を必ず通す
  - 401 / 402 / 422 は即停止。429 / 529 のみ指数バックオフで最大3回再試行
  - レスポンスの usage.usd（実額）を返す。推定値を自前で持たない
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from . import config, guard

BASE_URL = "https://api.pixellab.ai/v2"

#: 再試行してよい HTTP ステータス。これ以外は再試行しない。
RETRYABLE_STATUS = frozenset({429, 529})

#: 再試行の上限回数と初期待ち時間（秒）。指数バックオフ。
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2.0

#: 非同期ジョブのポーリング間隔（秒）と上限時間。
POLL_INTERVAL_SECONDS = 6.0
POLL_TIMEOUT_SECONDS = 600.0


class ProviderError(Exception):
    """通信層の失敗。握り潰さず必ず呼び出し側へ伝える。"""


class AuthError(ProviderError):
    """401。キーが不正。再試行しない。"""


class InsufficientCreditsError(ProviderError):
    """402。残高不足。再試行しない。"""


class ValidationError(ProviderError):
    """422。パラメータ不正。再試行しても無駄なので再試行しない。"""


class RateLimitError(ProviderError):
    """429 / 529。再試行の対象。"""


def resolve_api_key(provider: str) -> str:
    """provider に対応する環境変数から APIキーを読む。

    値は返すだけで、表示もログ出力も一切しない。
    """
    env_name = config.PROVIDER_ENV.get(provider)
    if env_name is None:
        raise ProviderError("未知の provider: " + repr(provider))
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise ProviderError(
            "環境変数 " + env_name + " が設定されていません。\n"
            "設定方法は .env.example を参照してください。"
            "値をリポジトリのファイルに書かないこと。"
        )
    # 形だけ検査して、明らかに壊れた値のまま送信して 401 を食うのを防ぐ。
    # 値そのものは絶対に表示しない。長さと文字種だけを見る。
    try:
        key.encode("ascii")
    except UnicodeEncodeError:
        raise ProviderError(
            "環境変数 " + env_name + " に非 ASCII 文字が含まれています"
            "（長さ " + str(len(key)) + " 文字）。\n"
            "APIキーは ASCII の英数字と記号のみで構成されます。"
            "日本語などが混入していないか確認してください。\n"
            "※値は表示しません。"
        ) from None
    if len(key) < 16:
        raise ProviderError(
            "環境変数 " + env_name + " の値が短すぎます"
            "（長さ " + str(len(key)) + " 文字）。\n"
            "PixelLab のトークンは UUID 形式の 36 文字です。"
            "値が途中で切れていないか確認してください。\n"
            "※値は表示しません。"
        )
    return key


def _request(url: str, api_key: str, payload: dict | None, method: str = "POST") -> tuple:
    """1回だけ HTTP を叩く。(status, body) を返す。例外は投げない。"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + api_key)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8") or "{}")
        except (ValueError, OSError):
            body = {}
        return exc.code, body
    except urllib.error.URLError as exc:
        raise ProviderError("ネットワークに到達できません: " + str(exc.reason)) from None


def _raise_for_status(status: int, body: dict, context: str) -> None:
    """ステータスを例外に振り分ける。キーは絶対に文面へ入れない。"""
    detail = ""
    if isinstance(body, dict):
        detail = str(body.get("detail") or body.get("message") or "")[:400]
    if status == 401:
        raise AuthError(
            context + ": 401 認証に失敗しました。APIキーが不正か失効しています。\n"
            "再試行しません。キーを確認してください（値は出力しません）。" +
            ("\nサーバ応答: " + detail if detail else "")
        )
    if status == 402:
        raise InsufficientCreditsError(
            context + ": 402 クレジットが不足しています。再試行しません。" +
            ("\nサーバ応答: " + detail if detail else "")
        )
    if status == 422:
        raise ValidationError(
            context + ": 422 パラメータが不正です。再試行しても解決しません。" +
            ("\nサーバ応答: " + detail if detail else "")
        )
    if status in RETRYABLE_STATUS:
        raise RateLimitError(context + ": " + str(status) + " レート制限。" + detail)
    if status >= 400:
        raise ProviderError(
            context + ": HTTP " + str(status) + " で失敗しました。" +
            ("\nサーバ応答: " + detail if detail else "")
        )


def _usd(body: dict) -> float:
    """レスポンスから実額（USD）を取り出す。無ければ 0.0。"""
    usage = (body or {}).get("usage") or {}
    try:
        return float(usage.get("usd") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def call(endpoint: str, payload: dict, provider: str = "pixellab",
         verbose: bool = True) -> tuple:
    """1件の生成リクエストを送り、(レスポンス, 実額USD) を返す。

    202 が返った場合は完了までポーリングする。
    送信前に必ず参照画像ガードを通す。
    """
    guard.assert_safe_request(payload, where=endpoint)

    api_key = resolve_api_key(provider)
    url = BASE_URL + endpoint
    total_usd = 0.0

    last_error: ProviderError | None = None
    for attempt in range(MAX_RETRIES + 1):
        if attempt:
            wait = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            if verbose:
                print("  レート制限のため %.0f 秒待って再試行します (%d/%d)"
                      % (wait, attempt, MAX_RETRIES))
            time.sleep(wait)
        status, body = _request(url, api_key, payload)
        try:
            _raise_for_status(status, body, endpoint)
        except RateLimitError as exc:
            last_error = exc
            continue
        break
    else:
        raise ProviderError(
            "レート制限が " + str(MAX_RETRIES) + " 回の再試行でも解消しませんでした。"
            "これ以上は自動で再試行しません。時間をおいて実行してください。\n"
            + str(last_error)
        )

    total_usd += _usd(body)

    job_id = body.get("background_job_id")
    if status == 202 or job_id:
        body, poll_usd = _poll(job_id, api_key, verbose=verbose)
        total_usd += poll_usd

    return body, total_usd


def _poll(job_id: str, api_key: str, verbose: bool = True) -> tuple:
    """非同期ジョブの完了を待つ。(最終レスポンス, 実額USD) を返す。"""
    if not job_id:
        raise ProviderError("非同期ジョブIDが返りませんでした。")
    url = BASE_URL + "/background-jobs/" + str(job_id)
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    total_usd = 0.0
    waited = 0.0

    while time.monotonic() < deadline:
        status, body = _request(url, api_key, None, method="GET")
        if status == 423:
            time.sleep(POLL_INTERVAL_SECONDS)
            waited += POLL_INTERVAL_SECONDS
            continue
        _raise_for_status(status, body, "background-jobs")
        total_usd += _usd(body)
        state = str(body.get("status") or "").lower()
        if state in ("completed", "succeeded", "success"):
            return body.get("last_response") or body, total_usd
        if state in ("failed", "error"):
            raise ProviderError(
                "生成ジョブが失敗しました: " + str(body.get("error") or body)[:400]
            )
        if verbose and waited and waited % 30 < POLL_INTERVAL_SECONDS:
            print("  生成中… %.0f 秒経過" % waited)
        time.sleep(POLL_INTERVAL_SECONDS)
        waited += POLL_INTERVAL_SECONDS

    raise ProviderError(
        "生成ジョブが %.0f 秒以内に完了しませんでした。job_id=%s"
        % (POLL_TIMEOUT_SECONDS, job_id)
    )


def extract_images(body: dict) -> list:
    """レスポンスから base64 画像を取り出して bytes のリストで返す。"""
    import base64
    import re as _re

    found: list = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if node.get("type") == "base64" and isinstance(node.get("base64"), str):
                found.append(node["base64"])
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)
        elif isinstance(node, str) and node.startswith("data:image/"):
            found.append(node)

    walk(body)

    out = []
    for item in found:
        payload = _re.sub(r"^data:image/[a-zA-Z0-9.+-]+;base64,", "", item)
        try:
            out.append(base64.b64decode(payload))
        except Exception:  # noqa: BLE001 - 壊れた1枚で全体を落とさない
            continue
    return out
