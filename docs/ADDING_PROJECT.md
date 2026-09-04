# 新規プロジェクトの追加手順

所要時間の目安は **5分**。実質的な作業は手順3のコマンド1回である。

## 前提

```bash
git lfs install
python -m pip install -r requirements.txt
```

## 1. プロジェクトIDを決める（1分）

- **小文字英数とハイフンのみ**（`^[a-z0-9][a-z0-9-]*$`）。40文字以内。
- ディレクトリ名とログファイル名になるため、後から変更しにくい。決めきること。
- 既存と重複しないこと。確認は `ls projects/`。

## 2. ブランチを切る（10秒）

```bash
git switch -c chore/add-<project_id>
```

`main` への直接コミットは禁止。

## 3. 雛形から生成する（1分）

```bash
python tools/new_project.py \
    --id <project_id> \
    --title "<作品タイトル>" \
    --description "<一行説明>" \
    --tile-size 32 \
    --resolution 640x360 \
    --colors 64 \
    --engine godot \
    --engine-version 4.7 \
    --normalmap
```

作られるものを事前に確認したい場合は `--dry-run` を付ける。

| オプション | 必須 | 内容 |
| --- | --- | --- |
| `--id` | ○ | プロジェクトID |
| `--title` | ○ | 作品タイトル（日本語可） |
| `--tile-size` | ○ | タイル1辺のピクセル数 |
| `--resolution` | ○ | 基準解像度（`640x360` 形式） |
| `--colors` | ○ | 色数の上限 |
| `--description` | | 一行説明 |
| `--engine` / `--engine-version` | | 既定は `godot` / `4.7` |
| `--categories` | | 既定は `tilesets objects overhead ui icons` |
| `--provider` | | 既定は `pixellab` |
| `--normalmap` | | ノーマルマップを使う構成にする |
| `--force` | | 既存ディレクトリを上書きする |

生成されるもの:

```
projects/<id>/project.yaml          設定（コマンドの引数がここに書き込まれる）
projects/<id>/PROGRESS.md           進捗管理
projects/<id>/style/                STYLE_GUIDE.md と base_prompt.md
projects/<id>/palettes/             空
projects/<id>/requirements/         空
projects/<id>/assets/<category>/    カテゴリごとに空ディレクトリ
projects/<id>/refs/                 空（Git 追跡外）
projects/<id>/_work/                空（Git 追跡外）
logs/generation_log.<id>.jsonl      空
```

スクリプトは最後に `project.yaml` を読み直して検証する。
エラーが出なければ設定はスキーマに適合している。

## 4. 除外が効いていることを確認する（1分）

参考画像と中間生成物が Git に入らないことを、実際に確かめる。

```bash
mkdir -p projects/<id>/refs projects/<id>/_work
echo dummy > projects/<id>/refs/dummy.png
echo dummy > projects/<id>/_work/dummy.png
git status --porcelain --untracked-files=all projects/<id>
```

**`refs/` と `_work/` のファイルが1つも出てこないこと。** 出てきたら
`.gitignore` を確認する。確認後、ダミーは削除する。

```bash
rm projects/<id>/refs/dummy.png projects/<id>/_work/dummy.png
```

LFS の対象範囲も確認しておく。

```bash
git check-attr filter -- projects/<id>/assets/tilesets/sample.png      # → filter: lfs
git check-attr filter -- projects/<id>/_work/raw_001.png               # → filter: unspecified
```

## 5. コミットして PR を出す（1分）

```bash
git add .
git commit -m "chore(<project_id>): プロジェクトの器を追加"
git push -u origin chore/add-<project_id>
gh pr create --base main
```

PR 本文には 概要／変更点／確認方法／未対応・既知の課題 を含める。

## 作成後にやること

雛形は器だけを作る。中身は順に埋めていく。

| 順 | 作業 | 置き場所 |
| --- | --- | --- |
| 1 | パレットを決める | `projects/<id>/palettes/` |
| 2 | `project.yaml` の `palette.file` にパレットのパスを書く | `projects/<id>/project.yaml` |
| 3 | スタイルガイドを埋める | `projects/<id>/style/STYLE_GUIDE.md` |
| 4 | ベースプロンプトを書く | `projects/<id>/style/base_prompt.md` |
| 5 | 素材要件を洗い出す | `projects/<id>/requirements/` |
| 6 | 参考画像を集める | `projects/<id>/refs/`（Git には入らない） |
| 7 | `generation.model` を確定する | `projects/<id>/project.yaml` |

## つまずいたら

| 症状 | 原因と対処 |
| --- | --- |
| `不正なプロジェクトID` | 大文字・アンダースコア・記号が入っている。小文字英数とハイフンのみ |
| `既に存在します` | 同名のプロジェクトがある。ID を変えるか `--force` |
| `PyYAML が見つかりません` | `python -m pip install -r requirements.txt` |
| `refs/` の中身が `git status` に出る | `.gitignore` に `**/refs/` があるか確認。`!` の例外を足していないか確認 |
| 完成品 PNG が LFS に入らない | `git lfs install` を実行したか確認。パスが `projects/<id>/assets/` 配下か確認 |
