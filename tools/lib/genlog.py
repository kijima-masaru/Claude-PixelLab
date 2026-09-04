"""生成ログ（JSONL）の読み書き。

ログはプロジェクト別ファイル logs/generation_log.<project_id>.jsonl に
1行1レコードで追記する。横断集計は複数ファイルを読んで行う。

このログが「中間生成物を捨ててよい」根拠になる。したがって
シード・プロンプト全文・全パラメータ・モデル名は必ず記録すること。
採用しなかった候補も adopted=false と reject_reason を添えて残すこと。

API キーおよびそれに類する値は絶対に書き込まない。書き込み時に機械的に弾く。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Iterator

from . import config

LOG_PREFIX = "generation_log."
LOG_SUFFIX = ".jsonl"

#: この語を含むキーはログに書かせない。値の中身は検査せず、キー名だけで弾く。
_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|apikey|secret|token|password|passwd|credential|authorization|bearer)",
    re.IGNORECASE,
)

#: 1レコードの項目。順序はそのまま JSONL の出力順になる。
FIELDS = (
    "timestamp",       # ISO8601（生成時刻）
    "project_id",      # プロジェクトID
    "run_id",          # 実行単位ID。_work/<run_id>/ と対応する
    "provider",        # 生成サービス識別子
    "model",           # モデル名
    "model_version",   # モデルのバージョン
    "prompt",          # プロンプト全文
    "negative_prompt", # ネガティブプロンプト全文
    "params",          # 全パラメータ（dict）
    "seed",            # シード
    "output_path",     # 生出力のパス（_work 配下。消えていてよい）
    "asset_path",      # 採用時の完成品パス（assets 配下）
    "adopted",         # 採否（bool）
    "reject_reason",   # 不採用理由を1行で
    "estimated_cost",  # 推定コスト
    "source",          # 由来。他プロジェクトからの流用時に記録する
)


class LogError(Exception):
    """ログの読み書きに失敗したことを表す。"""


def log_path(project_id: str) -> Path:
    """logs/generation_log.<project_id>.jsonl を返す。"""
    config.validate_project_id(project_id)
    return config.LOGS_DIR / f"{LOG_PREFIX}{project_id}{LOG_SUFFIX}"


def list_log_files(project_ids: Iterable[str] | None = None) -> list[Path]:
    """対象ログファイルを返す。project_ids 未指定なら全プロジェクト分。"""
    if project_ids is not None:
        return [log_path(pid) for pid in project_ids]
    if not config.LOGS_DIR.is_dir():
        return []
    return sorted(config.LOGS_DIR.glob(f"{LOG_PREFIX}*{LOG_SUFFIX}"))


def assert_no_secrets(record: dict, _path: str = "") -> None:
    """機密を思わせるキーが含まれていないことを確認する。含まれていれば例外。"""
    for key, value in record.items():
        here = f"{_path}.{key}" if _path else str(key)
        if _SECRET_KEY_RE.search(str(key)):
            raise LogError(
                f"ログに機密項目を書こうとしています: {here} / "
                "APIキーやトークンはログ・コード・ドキュメントのいずれにも残さないこと。"
            )
        if isinstance(value, dict):
            assert_no_secrets(value, here)


def append(record: dict) -> Path:
    """1レコードを該当プロジェクトのログに追記し、書き込み先を返す。"""
    project_id = record.get("project_id")
    if not project_id:
        raise LogError("project_id のないレコードは記録できません。")
    assert_no_secrets(record)
    ordered = {k: record[k] for k in FIELDS if k in record}
    ordered.update({k: v for k, v in record.items() if k not in FIELDS})
    path = log_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(ordered, ensure_ascii=False) + "\n")
    return path


def iter_records(project_ids: Iterable[str] | None = None) -> Iterator[dict]:
    """対象ログのレコードを順に返す。横断集計はこれを使う。"""
    for path in list_log_files(project_ids):
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise LogError(f"{path}:{lineno}: JSON として読めません: {exc}") from None


def find_run(run_id: str, project_ids: Iterable[str] | None = None) -> list[dict]:
    """run_id に一致するレコードを返す。regenerate.py が使う。"""
    return [r for r in iter_records(project_ids) if r.get("run_id") == run_id]
