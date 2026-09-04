# Claude-PixelLab

複数のゲームプロジェクトのドット絵素材を、1つのリポジトリで制作・管理する。

このリポジトリが持つのは **素材とその制作パイプラインだけ** である。
ゲーム本体のコードは別リポジトリにあり、完成した素材はそちらへ取り込まれる。

## 目次

- [構成](#構成)
- [セットアップ](#セットアップ)
- [制作の流れ](#制作の流れ)
- [中間生成物を残さない方針](#中間生成物を残さない方針)
- [ツールの使い方](#ツールの使い方)
- [プロジェクトを追加する](#プロジェクトを追加する)
- [ゲーム本体リポジトリとの関係](#ゲーム本体リポジトリとの関係)
- [次のステップ](#次のステップ)

## 構成

```
.
├── docs/                  リポジトリ全体の規約と手順書
├── schema/                project.yaml のスキーマ定義
├── tools/                 全プロジェクト共通のツール群
│   └── lib/               設定読み込みとログ入出力の共有ライブラリ
├── templates/project/     新規プロジェクトの雛形
├── projects/<project_id>/ プロジェクト固有のもの一式
├── logs/                  生成ログ（プロジェクト別 JSONL・Git 管理・LFS 対象外）
└── requirements.txt
```

プロジェクト1つの中身:

```
projects/<project_id>/
├── project.yaml       このプロジェクトの唯一の設定元（解像度・タイル・色数・エンジン等）
├── PROGRESS.md        進捗管理
├── style/             スタイルガイドとベースプロンプト
├── palettes/          パレット
├── requirements/      素材要件（何を何枚作るか）
├── assets/<category>/ 完成品。ここだけが Git LFS 管理
├── refs/              参考画像。★Git 追跡外・ローカルのみ
└── _work/             中間生成物。★Git 追跡外・ローカルのみ
```

共有するのは `tools/` `docs/` `logs/`、分けるのは `projects/<project_id>/` 配下、
という2層だけの構造にしている。プロジェクトが2〜5個の規模を想定している。

## セットアップ

```bash
git clone git@github.com:kijima-masaru/Claude-PixelLab.git
cd Claude-PixelLab
git lfs install
python -m pip install -r requirements.txt
```

APIキーは環境変数から読む。**リポジトリには一切置かない。**
必要な変数名は [.env.example](.env.example) にある。

```powershell
# PowerShell
$env:PIXELLAB_API_KEY = "..."
```

```bash
# bash
export PIXELLAB_API_KEY="..."
```

`.env` `.env.*` は `.gitignore` で除外済み。キーをコード・ログ・ドキュメント・
コミットメッセージのいずれにも書かないこと。

## 制作の流れ

```
1. 要件を書く        projects/<id>/requirements/
2. 生成する          tools/client.py    → _work/<run_id>/ に生出力 + ログ記録
3. 採否を決める      採用・不採用いずれもログに残す（不採用は理由を1行）
4. 後処理する        tools/postprocess.py → assets/<category>/ に完成品
5. 検査する          tools/validate_assets.py
6. 法線を作る        tools/normalmap.py（必要なプロジェクトのみ）
7. _work/ を捨てる   ログを書き終えていれば削除してよい
```

## 中間生成物を残さない方針

**API の生出力（中間生成物）は Git にも LFS にもコミットしない。**
`projects/<id>/_work/` に置き、`.gitignore` で除外している。
LFS に入れてよいのは後処理済みの完成品 PNG だけである。

理由は2つ。

1. **LFS の帯域と容量には上限がある。** 採用1枚あたり数枚〜数十枚の候補が出る
   ワークフローで生出力まで LFS に入れると、早期に枯渇する。
2. **中間生成物そのものに価値はない。** 価値があるのは「それを作った条件」である。

**再現性の担保は「完成品が Git LFS にあること」である。**

当初はシードとプロンプトからの再生成を担保にする設計だったが、
**PixelLab API には `seed` パラメータが存在する。しかし実測の結果、
同一シード・同一パラメータで再送しても同一の画像は得られなかった**
（64×64 の同一条件2回で 37.9% の画素が相違）。したがって seed は
「傾向を揃えるための手がかり」にはなるが、**復元の手段にはならない。**
したがって **LFS 上の完成品が唯一の再現性の担保**であり、
完成品の LFS 管理は当初想定より重要度が上がっている。

生成ログの役割は次の3つである。

1. 何をいくらで作ったかの記録（コスト管理）
2. **同条件での引き直し**のための条件保存（同一画像の復元ではない）
3. 採否と不採用理由の蓄積（プロンプト改善のため）

生成のたびに `logs/generation_log.<project_id>.jsonl` へ以下を記録する。

日時 / プロジェクトID / run_id / provider / モデル名 / モデルバージョン /
プロンプト全文 / ネガティブプロンプト全文 / 全パラメータ / エンドポイント /
出力パス / 完成品パス / 採否 / 不採用理由 / 実額（`usage.usd`）

`seed` は指定した値をそのまま記録する。ただし**同一シードでも同一画像にはならない**
（実測済み）ため、これは復元用ではなく条件記録である。未指定の場合は `null` を記録し、
理由を `seed_note` に併記する。

**採用しなかった候補も、そのプロンプトと全パラメータを必ず残す。** 不採用理由を1行
添えることで、後から「その方向は試して駄目だった」と分かるようにする。

**APIキーおよびそれに類する値はログに書かない。** `tools/lib/genlog.py` が
書き込み時にキー名で機械的に弾く。

### `_work/` の運用

| 項目 | 内容 |
| --- | --- |
| 置き場所 | `projects/<project_id>/_work/<run_id>/` |
| `run_id` | `20260904-143052-a1b2` 形式。ログの `run_id` と1対1で対応する |
| 消してよい条件 | **完成品が `assets/` にある（＝LFS に入った）か、不採用としてログに `adopted: false` と理由を書き終えた状態。** 採用したものは LFS の完成品が唯一の原本になる |
| 消してはいけないもの | ログ未記載の生成物。これは「ログを書き忘れた」というバグの表れ |
| ディスク圧迫時 | 上記を満たしていれば `_work/` を丸ごと削除してよい |

**画像そのものの復元はできない。** 引き直したい場合はログの条件で再生成する。

```bash
python tools/regenerate.py --project <project_id> --run-id <run_id> --dry-run
python tools/regenerate.py --project <project_id> --run-id <run_id>
```

得られるのは「当時と同じ条件で引いた別の画像」である。同一画像が必要なら、
`assets/` にある完成品（LFS 管理）を使うこと。

## ツールの使い方

**すべてのツールは `--project <project_id>` を取る。** ツール側にプロジェクト名や
プロジェクト固有の値は書かない。解像度・タイルサイズ・色数はすべて
`projects/<id>/project.yaml` から読む。

| コマンド | 用途 |
| --- | --- |
| `tools/new_project.py` | 雛形から新規プロジェクトを作る |
| `tools/client.py` | 素材を生成する。`--dry-run` で送信内容だけ確認できる |
| `tools/postprocess.py` | パレット適用・グリッド整列・アンチエイリアス除去 |
| `tools/validate_assets.py` | パレット適合・グリッド・透明度の検査 |
| `tools/normalmap.py` | ノーマルマップ生成 |
| `tools/regenerate.py` | ログの条件で**同条件の引き直し**（同一画像の復元はできない） |
| `tools/cost_report.py` | ログをプロジェクト別・期間別に集計 |
| `tools/validate_fields.py` | フィールド定義の接続と素材IDを検証 |
| `tools/aggregate_assets.py` | 素材要件を API のコール単位で集計 |

各コマンドの詳細は `--help` を参照。

```bash
python tools/client.py --project iwato --prompt "..." --dry-run
```

### 安全弁

- **参照画像を送らない。** 送信直前に `tools/lib/guard.py` が検査し、
  違反があれば送信を止める。回帰テストは `python tests/test_guard.py`
- **上限。** `--max-images` と `--max-cost` のどちらか先に達した時点で停止する
- **失敗を握り潰さない。** 401 / 402 / 422 は即停止、429 / 529 のみ
  指数バックオフで最大3回再試行する

### ノーマルマップ

`tools/normalmap.py` で**ローカル生成する。API は使わない。**
**Godot では法線の Y 軸を反転する必要がある**（本ツールは既定で反転して出力する）。
詳細と Laigter を使う場合の注意は [docs/NORMALMAP.md](docs/NORMALMAP.md)。

## プロジェクトを追加する

```bash
python tools/new_project.py --id <project_id> --title "<タイトル>" \
    --tile-size 32 --resolution 640x360 --colors 64 \
    --engine godot --engine-version 4.7 --normalmap
```

プロジェクトIDは**小文字英数とハイフンのみ**。詳細な手順は
[docs/ADDING_PROJECT.md](docs/ADDING_PROJECT.md)。

## ゲーム本体リポジトリとの関係

```
Claude-PixelLab (このリポジトリ)          ゲーム本体リポジトリ
  projects/<id>/assets/  ──────────►  res://assets/ など
        完成品のみ                        取り込み先
```

- 受け渡すのは `projects/<project_id>/assets/` 配下の完成品だけ。
  `_work/` と `refs/` は渡さない（そもそも Git に存在しない）。
- 取り込み方法（サブモジュール／コピー／CI）は各ゲーム側の判断に委ねる。
  このリポジトリはゲーム側の構造に依存しない。
- `project.yaml` の `output`（filter / mipmaps / compression）は
  **エンジン側のインポート設定と必ず一致させること。** 食い違うと
  ドット絵が滲む。

## 次のステップ

[docs/NEXT_STEPS.md](docs/NEXT_STEPS.md) に申し送りをまとめている。

## 規約

**素材を作る前に [docs/PILOT_FINDINGS.md](docs/PILOT_FINDINGS.md) を読むこと。**
エンドポイントごとに投影が違う、タイルセットに書いた特徴は全タイルに複製される、
といった実測の知見がまとまっている。知らずに進むと作り直しになる。

命名規則・ディレクトリ規約・コミット規約・素材の品質基準は
[docs/CONVENTIONS.md](docs/CONVENTIONS.md) を参照。
ノーマルマップの扱いは [docs/NORMALMAP.md](docs/NORMALMAP.md) を参照。

## テスト

```bash
python tests/test_guard.py          # 参照画像ガードの回帰テスト
python tools/validate_fields.py --project iwato --strict
```
