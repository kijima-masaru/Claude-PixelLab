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
| Q W E R | 段階 0〜3 |
| L | ライトの入切 |
| N | ノーマルマップの入切 |
| S | スクリーンショット（`user://`） |

## 段階

**何がどれだけ効いたかを切り分けるためにある。**

| 段階 | 何が入るか | シェーダ |
| --- | --- | --- |
| 0 | 光と法線だけ | **無し** |
| 1 | ＋ 落ち影（遮蔽・形の投影・接地の陰り・太陽） | **無し** |
| 2 | ＋ 立ち物の法線を「形から起こしたもの」へ | **無し** |
| 3 | ＋ シェーダ3種 | 有り |

比較用の絵を一括で撮って終了する:

```bash
godot --path godot_preview -- --auto      # 時間帯ごと
godot --path godot_preview -- --stages    # 段階ごと
godot --path godot_preview -- --shadows   # 影の作り方4通り
godot --path godot_preview -- --sweep     # Light2D.height の総当たり（第22節）
```

## **正直に書いておくこと**

### シェーダで作ったもの（段階3だけ）

**この3つだけである。** 他は素材と Godot 標準のノードで出ている。

1. **ブルーム** — 明るい所を抜き出してにじませ、加算する。
   **夜だけ強く、昼はほぼ切る**（一律に掛けたら真昼の自販機が光る箱になった）
2. **濡れた路面の映り込み** — 車道の帯にだけ、上の画面を折り返して薄く重ねる
3. **光の減衰カーブ** — 二乗から、芯を持たせて裾を長く引く形へ

**段階0〜2 はシェーダを1行も使っていない。** 落ち影も、形から起こした
法線も、素材と標準ノードだけで出ている。**どこからが後処理かは段階で分かる。**

### シェーダで作っていないもの

- 落ち影（`LightOccluder2D` ＋ シルエットの投影 ＋ 接地の陰り）
- 立ち物の陰影（`shape_normalmap.py` が作った `_s.png`）
- 時間帯の色（`CanvasModulate`）

### その他

- **時間帯は CanvasModulate の色調の乗算で近似している。**
  本来の設計（時間帯ごとにパレットを差し替える）はシェーダで行うもので、
  ここではやっていない。**色の出方は本番と一致しない。**
- 地形は F01（国道沿い）を模した仮組みであり、**フィールドの正式な配置ではない。**
- 影の濃さは**撮った画素を測って**決めた（PILOT_FINDINGS 第26節）。
