# 見え方の確認用 Godot プロジェクト

**ゲーム本体ではない。** 納品済みの素材を**そのまま**読み、
2Dライトとノーマルマップを乗せて、**光を当てた後の見え方**を確かめるためだけのもの。
素材の作り直しは一切しない。

Godot 4.7 / 640×360 / Nearest / ミップマップ無し / stretch mode viewport。

## 使い方

`assets` は `projects/iwato/assets` へのリンクである。**リポジトリには入れない。**
clone した直後に自分で作る。

```powershell
# Windows
New-Item -ItemType Junction -Path godot_preview\assets -Target projects\iwato\assets
```

```bash
# macOS / Linux
ln -s ../projects/iwato/assets godot_preview/assets
```

ノーマルマップ（`<name>_n.png`）が無ければ先に作る。

```bash
python tools/normalmap.py --project iwato
```

起動する。

```bash
godot --path godot_preview
```

| キー | 動作 |
| --- | --- |
| 1〜4 | 朝・昼・夕・夜 |
| L | ライトの入切 |
| N | ノーマルマップの入切 |
| S | スクリーンショット（`user://`） |

比較用の絵を一括で撮って終了する:

```bash
godot --path godot_preview -- --auto
```

`Light2D.height` の効きを総当たりで見る（[PILOT_FINDINGS 第22節](../docs/PILOT_FINDINGS.md)）:

```bash
godot --path godot_preview -- --sweep
```

## **正直に書いておくこと**

- **シェーダは1つも追加していない。** 見えているものは、素材そのものと
  Godot 標準の `PointLight2D` / `CanvasModulate` だけで出ている。
  ブルームも色調補正も掛けていない。
- **時間帯は CanvasModulate の色調の乗算で近似している。**
  本来の設計（時間帯ごとにパレットを差し替える）はシェーダで行うもので、
  ここではやっていない。**色の出方は本番と一致しない。**
- 地形は F01（国道沿い）を模した仮組みであり、**フィールドの正式な配置ではない。**
