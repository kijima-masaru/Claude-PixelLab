"""project.yaml の読み込みと検証、およびリポジトリ内パスの解決。

全ツールはこのモジュール経由でプロジェクト設定を読む。
プロジェクト名をツール側に書かないための唯一の入口である。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit(
        "PyYAML が見つかりません。次を実行してください:\n"
        "    python -m pip install -r requirements.txt"
    )

# --- リポジトリ内の固定パス -------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
PROJECTS_DIR = ROOT / "projects"
TEMPLATES_DIR = ROOT / "templates" / "project"
LOGS_DIR = ROOT / "logs"
SCHEMA_PATH = ROOT / "schema" / "project.schema.json"

#: Git 追跡外のディレクトリ名。new_project.py はこれらを明示的に作成する。
#: .gitignore で全階層除外しているため、雛形をコピーしても追跡されず、
#: クローン直後には存在しない。ゆえにコピーではなく明示生成が必要。
LOCAL_ONLY_DIRS = ("refs", "_work")

#: プロジェクトID の書式。小文字英数とハイフンのみ。
PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: 生成サービスと、そのAPIキーを保持する環境変数名の対応。
#: キーの「値」はここにも他のどこにも書かない。
PROVIDER_ENV = {
    "pixellab": "PIXELLAB_API_KEY",
}


def _force_utf8_stdio() -> None:
    """標準出力を UTF-8 にする。

    Windows のコンソール既定コードページ（cp932 等）のままだと、
    日本語のヘルプやメッセージが文字化けするため。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass


_force_utf8_stdio()


class ConfigError(Exception):
    """設定の読み込み・検証に失敗したことを表す。"""


# --- パス解決 ---------------------------------------------------------------

def validate_project_id(project_id: str) -> str:
    """プロジェクトID の書式を検証して返す。"""
    if not PROJECT_ID_RE.match(project_id or ""):
        raise ConfigError(
            f"不正なプロジェクトID: {project_id!r} / "
            "小文字英数とハイフンのみ、先頭は英数字にすること。"
        )
    return project_id


def project_dir(project_id: str) -> Path:
    """projects/<project_id>/ を返す。"""
    return PROJECTS_DIR / validate_project_id(project_id)


def work_dir(project_id: str, run_id: str | None = None) -> Path:
    """中間生成物の作業ディレクトリ projects/<id>/_work/[<run_id>/] を返す。

    ここに置いたものは Git にも LFS にも入らない。ログを書き終えたら削除してよい。
    """
    base = project_dir(project_id) / "_work"
    return base / run_id if run_id else base


def refs_dir(project_id: str) -> Path:
    """参考画像ディレクトリ projects/<id>/refs/ を返す（Git 追跡外）。"""
    return project_dir(project_id) / "refs"


def assets_dir(project_id: str) -> Path:
    """完成品ディレクトリ projects/<id>/assets/ を返す（LFS 管理）。"""
    return project_dir(project_id) / "assets"


def list_projects() -> list[str]:
    """project.yaml を持つプロジェクトID を昇順で返す。"""
    if not PROJECTS_DIR.is_dir():
        return []
    return sorted(
        p.name for p in PROJECTS_DIR.iterdir()
        if (p / "project.yaml").is_file()
    )


# --- 読み込みと検証 ---------------------------------------------------------

def load_schema() -> dict:
    """schema/project.schema.json を読む。"""
    with SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_project(project_id: str, validate: bool = True) -> dict:
    """projects/<project_id>/project.yaml を読み、検証して返す。"""
    path = project_dir(project_id) / "project.yaml"
    if not path.is_file():
        known = ", ".join(list_projects()) or "(なし)"
        raise ConfigError(
            f"プロジェクト設定が見つかりません: {path}\n"
            f"既存のプロジェクト: {known}\n"
            "新規作成は: python tools/new_project.py --id <project_id> ..."
        )
    with path.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    if not isinstance(cfg, dict):
        raise ConfigError(f"{path} の内容がマッピングではありません。")
    if validate:
        validate_config(cfg, source=str(path))
    if cfg.get("id") != project_id:
        raise ConfigError(
            f"{path}: id が {cfg.get('id')!r} だがディレクトリ名は {project_id!r}。一致させること。"
        )
    return cfg


def validate_config(cfg: dict, source: str = "<config>") -> None:
    """設定を schema/project.schema.json に照らして検証する。

    jsonschema が入っていれば厳密に検証し、無ければ必須項目のみを検査する。
    依存を増やさずに済ませるための二段構えで、スキーマファイル自体が常に正典。
    """
    try:
        import jsonschema  # type: ignore
    except ImportError:
        _validate_minimal(cfg, source)
        return
    try:
        jsonschema.validate(cfg, load_schema())
    except jsonschema.ValidationError as exc:  # pragma: no cover
        loc = "/".join(str(p) for p in exc.absolute_path) or "(ルート)"
        raise ConfigError(f"{source}: {loc}: {exc.message}") from None


_REQUIRED_PATHS = (
    ("id",),
    ("title",),
    ("engine", "name"),
    ("engine", "version"),
    ("canvas", "tile_size"),
    ("canvas", "base_resolution", "width"),
    ("canvas", "base_resolution", "height"),
    ("palette", "max_colors"),
    ("output", "format"),
    ("output", "filter"),
    ("output", "mipmaps"),
    ("output", "compression"),
    ("asset_categories",),
    ("generation", "provider"),
)


def _validate_minimal(cfg: dict, source: str) -> None:
    """jsonschema 不在時の最小検証。必須項目の存在と主要な型のみ見る。"""
    for path in _REQUIRED_PATHS:
        node = cfg
        for key in path:
            if not isinstance(node, dict) or key not in node:
                raise ConfigError(f"{source}: 必須項目がありません: {'.'.join(path)}")
            node = node[key]
    validate_project_id(cfg["id"])
    if not isinstance(cfg["canvas"]["tile_size"], int):
        raise ConfigError(f"{source}: canvas.tile_size は整数にすること。")
    if not isinstance(cfg["palette"]["max_colors"], int):
        raise ConfigError(f"{source}: palette.max_colors は整数にすること。")
    if not isinstance(cfg["asset_categories"], list) or not cfg["asset_categories"]:
        raise ConfigError(f"{source}: asset_categories は空でない配列にすること。")
    provider = cfg["generation"]["provider"]
    if provider not in PROVIDER_ENV:
        known = ", ".join(sorted(PROVIDER_ENV))
        raise ConfigError(f"{source}: 未知の provider: {provider!r} / 既知: {known}")


# --- CLI 共通 ---------------------------------------------------------------

def add_project_arg(parser: argparse.ArgumentParser, required: bool = True) -> None:
    """全ツール共通の --project 引数を追加する。"""
    parser.add_argument(
        "--project", "-p",
        required=required,
        metavar="PROJECT_ID",
        help="対象プロジェクトID（例: iwato）。小文字英数とハイフンのみ。",
    )


def describe(cfg: dict) -> str:
    """設定の要約を1行で返す（ログ出力用）。"""
    res = cfg["canvas"]["base_resolution"]
    return (
        f"{cfg['id']} / {cfg['title']} / "
        f"tile={cfg['canvas']['tile_size']}px "
        f"res={res['width']}x{res['height']} "
        f"colors<={cfg['palette']['max_colors']} "
        f"engine={cfg['engine']['name']} {cfg['engine']['version']} "
        f"provider={cfg['generation']['provider']}"
    )
