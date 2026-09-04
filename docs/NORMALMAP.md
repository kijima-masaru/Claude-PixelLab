# ノーマルマップの作り方と使い方

『磐戸町奇譚』は 2Dライト + ノーマルマップで陰影を付ける。
このリポジトリでは **ノーマルマップを API では作らない。ローカルで生成する。**

対象は地面と大きなオブジェクト（タイルセット352枚 + objects 91点 = 443点）。
UI とアイコンには不要。**API コストは 0 である。**

---

## ⚠️ 最重要 — Godot では Y 軸を反転する必要がある

一般的なノーマルマップは **OpenGL 規約**（Y が上向き）で作られる。
一方 **Godot の 2D は Y 軸を下向きに取る。**

そのため、OpenGL 規約のノーマルマップをそのまま Godot に渡すと、
**陰影が上下逆になる。** 上から光が当たっているのに、
凸が凹んで見える（あるいはその逆になる）。

このリポジトリの `tools/normalmap.py` は **既定で Y 軸を反転して出力する。**
つまり **そのまま Godot で使える。**

```bash
python tools/normalmap.py --project iwato --category tilesets
```

反転を止めたい場合のみ `--no-flip-y` を付ける。**通常は指定しない。**

```bash
# 他エンジン向けに OpenGL 規約で出したいときだけ
python tools/normalmap.py --project iwato --category tilesets --no-flip-y
```

### 見分け方

Godot でライトを**上から**当てて、素材の**上側が明るく**なれば正しい。
上側が暗くなったら Y が反転していない。

---

## 生成方法

### 方式

| `--method` | 内容 | 用途 |
| --- | --- | --- |
| `sobel`（既定） | 3×3 のソーベル演算子で勾配を求める | ほぼ全ての素材 |
| `height` | 前方差分。輪郭がより硬く出る | タイルの継ぎ目を強調したいとき |

輝度を高さとみなして法線を求める。**ぼかしを一切かけない。**
ドット絵の輪郭を保つためであり、ぼかすと 32px では輪郭が溶ける。

完全透明な画素は法線を計算せず、アルファ 0 のまま残す。

### 強さ

```bash
python tools/normalmap.py --project iwato --category objects --strength 1.5
```

`--strength` を上げると凹凸が強くなる。**1.0〜1.5 を基準にする。**
上げすぎると 32px では階段状のノイズが目立つ。

### 出力名

元素材と同じディレクトリに `<name>_n.png` として置く。

```
assets/tilesets/tile_asphalt_curb.png
assets/tilesets/tile_asphalt_curb_n.png   ← ノーマルマップ
```

`_n` は Godot の `CanvasTexture` で法線を紐づけるときの慣習に合わせている。
`normalmap.py` は `_n` で終わるファイルを入力から自動的に除外するため、
繰り返し実行してもノーマルマップのノーマルマップは作られない。

---

## Godot 4.7 側の設定

### インポート設定

ノーマルマップも**素材本体と同じ設定にする。**

| 項目 | 値 |
| --- | --- |
| Filter | **Nearest** |
| Mipmaps | **Off** |
| 圧縮 | **なし（Lossless）** |

**ノーマルマップを圧縮しないこと。** VRAM 圧縮をかけると法線の値が
わずかに崩れ、32px では陰影のムラとして見える。

### CanvasTexture

`Sprite2D` や `TileSet` のテクスチャに `CanvasTexture` を使い、

- `Diffuse Texture` … 素材本体
- `Normal Texture` … `<name>_n.png`

を割り当てる。`TileSet` の場合はタイルセットのテクスチャ自体を
`CanvasTexture` にする。

### 2Dライト

`PointLight2D` / `DirectionalLight2D` の光が法線に反応する。
`Light2D` の `Energy` と `Color` が、`project.yaml` の
`palette.max_colors` の範囲を超えて色を作り出す点に注意すること。
**ライトで作った中間色はパレット外の色になる。**
`validate_assets.py` の検査対象は素材ファイルであり、
実行時のライティング結果は検査できない。

---

## Laigter を使う場合

より作り込んだ法線が必要なときは、[Laigter](https://azagaya.itch.io/laigter)
（オープンソースの法線生成ツール）を使ってもよい。その場合の手順と注意。

### 手順

1. 完成品（`assets/<category>/*.png`）を Laigter に読み込む
2. パラメータを調整する
3. 書き出す（`<name>_n.png` の命名規則に合わせてリネームする）
4. **Godot に入れる前に Y 軸を反転する**（下記）

### ⚠️ 注意1 — Laigter の出力も Y 軸の反転が必要

Laigter は OpenGL 規約で書き出す。**Godot ではそのまま使えない。**

`tools/normalmap.py` を通した場合と違い、**反転は手作業になる。**
画像編集ソフトで緑チャンネル（G）だけを反転する。

```
Godot 用の法線 = (R, 255 - G, B)
```

Laigter 側に反転オプションがある場合はそれを使ってよいが、
**書き出したファイルで実際に反転されているかを必ず確認すること。**

### ⚠️ 注意2 — Pixelated / Toon オプションは書き出しに反映されない

Laigter の **`Pixelated`** と **`Toon`** のオプションは
**プレビュー表示のためのものであり、書き出されるファイルには反映されない。**

プレビューで「ドット絵らしい硬い陰影」に見えていても、
書き出したファイルは滑らかな法線のままである。
**プレビューを見て採否を判断しないこと。** 必ず書き出したファイルを
Godot に入れて確認すること。

この2点を知らないと、「Laigter では良く見えたのに Godot では
陰影が逆で、しかも滑らかすぎる」という状態になる。

### どちらを使うか

| | `tools/normalmap.py` | Laigter |
| --- | --- | --- |
| Y 軸反転 | **自動** | 手作業 |
| Pixelated/Toon の罠 | なし | **あり** |
| 一括処理 | できる（カテゴリ単位） | 1枚ずつ |
| 調整の自由度 | 低い（強さと方式のみ） | 高い |
| 再現性 | ログとスクリプトで担保 | 手作業のため残らない |

**443点を扱う以上、既定は `tools/normalmap.py` である。**
Laigter は「この1枚だけどうしても凝りたい」場合に限って使う。
その場合は、手作業であることを `PROGRESS.md` に書き残すこと。

---

## 確認

```bash
python tools/normalmap.py --project iwato --category tilesets --dry-run
python tools/normalmap.py --project iwato --category tilesets
python tools/validate_assets.py --project iwato --category tilesets
```

`validate_assets.py` は **`_n` で終わるファイルをパレット検査と透明度検査から
自動的に除外する。** 法線の色がパレット外になるのは正常だからである。
グリッドとサイズは法線にも適用される（素材本体と寸法が一致すべきなので）。

したがって、特別なオプションを付けずにそのまま実行してよい。
