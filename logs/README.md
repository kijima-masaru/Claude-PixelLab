# 生成ログ

素材生成の記録。**プロジェクト横断で1箇所（このディレクトリ）に集約し、
ファイルはプロジェクト別に分ける。**

```
logs/generation_log.<project_id>.jsonl
```

- 1行1レコードの JSONL。**追記のみ。**
- Git で管理する。**LFS 対象外**（テキストなので差分を追いたい）。
- 横断集計は複数ファイルを読んで行う。`tools/lib/genlog.py` の
  `iter_records()` がこれを担う。

## なぜプロジェクト別に分けるか

生成が数千件規模になると、単一ファイルでは検索性とリポジトリサイズの
両面で問題になる。プロジェクト別に分けても、集約先が1ディレクトリであれば
横断集計はできる。

## なぜログを消してはいけないか

**中間生成物（`_work/`）を Git に残さない方針の、唯一の担保がこのログである。**
生出力を捨ててもシードとプロンプトが残っていれば再生成できる、という前提で
運用している。ログを失うとその前提が崩れる。

```bash
python tools/regenerate.py --project <project_id> --run-id <run_id>
```

## 記録項目

正典は `tools/lib/genlog.py` の `FIELDS`。

| 項目 | 内容 |
| --- | --- |
| `timestamp` | 生成日時（ISO8601） |
| `project_id` | プロジェクトID |
| `run_id` | 実行単位ID。`projects/<id>/_work/<run_id>/` と対応 |
| `provider` | 生成サービス識別子 |
| `model` | モデル名 |
| `model_version` | モデルのバージョン |
| `prompt` | **プロンプト全文** |
| `negative_prompt` | ネガティブプロンプト全文 |
| `params` | **全パラメータ** |
| `seed` | **シード** |
| `output_path` | 生出力のパス（`_work/` 配下。消えていてよい） |
| `asset_path` | 採用時の完成品パス（`assets/` 配下） |
| `adopted` | 採否（真偽値） |
| `reject_reason` | **不採用の理由を1行で** |
| `estimated_cost` | 推定コスト |
| `source` | 由来。他プロジェクトからの流用時に記録する |

**採用しなかった候補も必ず記録する。** 不採用理由を1行添えることで、
後から「その方向は試して駄目だった」と分かるようにする。

## 書いてはいけないもの

**APIキーおよびそれに類する値。** `genlog.append()` が書き込み時に
キー名（`api_key` `token` `secret` `credential` 等）で機械的に弾くが、
値を別のキー名に入れれば通ってしまう。書かないこと。

## 集計

```bash
python tools/cost_report.py                    # 全プロジェクト横断
python tools/cost_report.py --project <id>     # プロジェクト単体
```

> 集計処理は未実装（次ステップ）。現状はログファイルの列挙とレコード数まで。
