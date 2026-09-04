# 自作物を参照画像として送るための設計

**これは設計だけである。実装していない。**

2026-09-04 時点で優先度は低い。タイルセットは手続き的生成で賄えることが
判明し、PixelLab に参照画像を送る場面がほぼ無くなったため
（[`PILOT_FINDINGS.md`](PILOT_FINDINGS.md) 第13節）。

**ただしオブジェクト91点・deco・UI・アイコンは未検証である。**
そこで参照画像が要る可能性は残っている。必要になったらこの設計で実装する。

---

## 何を解く設計か

`projects/<id>/refs/` には**第三者の著作物**が置かれる。これは
`.gitignore` と送信ガードの両方で守られている。

一方、**依頼者自身の著作物**（自作ゲームの画面、このリポジトリが生成した
完成品タイル）には、その制約が要らない。むしろ

- **Git にコミットしてよい**（著作者本人のもの）
- **API に送ってよい**（`lower_reference_image` 等で画風を固定できる）

**この2つを、同じ `refs/` に置いてはならない。** 混ざると、どちらの
規則を適用すべきか区別できなくなる。

---

## 置き場所

```
projects/<id>/style/own_reference/
    MANIFEST.yaml
    ground_asphalt_01.png
    roof_kawara_01.png
```

- `**/refs/` にも `**/_work/` にも当たらないため、**そのままコミットされる**
- **Git LFS には入れない。** LFS は `projects/*/assets/**/*.png` に限定されており、
  参考画像は完成品でも中間生成物でもない。`.gitattributes` の変更は不要
- **画面全体ではなく、切り出したパッチを置く。** 透視投影の画面全体を
  `lower_reference_image` に渡すと、遠近と建物の形まで学習させることになる。
  渡すべきは素材の質感だけである

---

## MANIFEST.yaml

**ディレクトリに置くだけでは送信できない。** マニフェストに
`send_to_api: true` と明記されたファイルだけをガードが通す。
取り違えて別のファイルを置いても事故にならない。

```yaml
schema_version: 1
project_id: iwato
entries:
  - file: ground_asphalt_01.png
    sha256: "<64桁>"
    origin: 依頼者自身の自作ゲームの画面から切り出したパッチ
    author: 依頼者本人
    send_to_api: true
    note: 透視投影を補正し、52色へ吸着済み
```

`sha256` は**中身と一致しなければ通さない**。差し替えを検出するため。

---

## ガードの改修

現在の [`tools/lib/guard.py`](../tools/lib/guard.py) は第1層で
参照画像パラメータを**名前で一律禁止**している（15種）。これを2つに分ける。

**恒久禁止**（名前だけで落とす。本作で使う予定がない）

    style_image / reference_image / concept_image /
    context_image / from_image / portrait / inpainting_image

なお `style_image` は**実仕様に存在しない**（`openapi.json` で確認済み）。
実在するのは以下である。

| エンドポイント | パラメータ |
| --- | --- |
| `/create-tileset` | `lower_reference_image` / `upper_reference_image` / `transition_reference_image` / `color_image` / `tileset_adherence`（追従の強さ。既定100 / 最大500） |
| `/map-objects` | `init_image` + `init_image_strength` / `background_image` + `inpainting` / `color_image` |
| `/create-image-pixflux` | `init_image` + `init_image_strength` / `color_image` |
| `/generate-ui-v2` | `concept_image`（UI 専用） |

**中身検査つき許可**（マニフェスト登録済みのものだけ通す）

    lower_reference_image / upper_reference_image /
    transition_reference_image / init_image / background_image / color_image

値の SHA-256 がマニフェストに載っていて `send_to_api: true` のときだけ通す。

> **これは現状より厳しい。** 今 `color_image` は「禁止名でなく refs/ でもない」
> という理由で素通りしているが、新設計では**登録済みの自作ファイルでなければ落ちる。**
> 「refs/ に無い」という消極的な条件から、「登録済みである」という
> **積極的な許可**へ変える。

**第2層・第3層はそのまま維持する。**

- refs/ 配下のパス検出
- refs/ のファイルとのハッシュ照合
- JPEG 拒否 — ただし**マニフェスト登録済みのファイルには適用しない**
  （運用上は own_reference/ を PNG に統一すれば衝突しない）

---

## 実装するときの確認事項

- `tests/test_guard.py` の26件が通ること
- **マニフェストに無いファイルが落ちること**を試験に加える
- **マニフェストに載っているが中身が変わったファイルが落ちること**も加える
- `describe_guard()` の1行表示に、許可リストの件数を含める
