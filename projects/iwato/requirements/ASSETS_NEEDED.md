# 素材要件（発注書）

> ## ⚠️ この発注書はパイロットの結果を受けて再編されました（2026-09-04）
>
> **「何を作るか」はこのファイル、「どう作るか」は
> [`production_plan.yaml`](production_plan.yaml) が持ちます。**
> 根拠は [`docs/PILOT_FINDINGS.md`](../../../docs/PILOT_FINDINGS.md)。
>
> 主な変更:
> - **建物14点を屋根タイルセット5本に集約**（真上見下ろしでは建物は屋根の面である）
> - **オブジェクトを高さで仕分けた。** 投影の問題は高さのある物にだけ起きる
> - **地面の装飾（白線・グレーチング・マンホール）を新設**し、`ground_detail` レイヤーへ
> - タイルセットから「たまにある特徴」を分離（3本該当）
> - **高さのある単体物24点は作り方が未解決**。ここだけが残っている


『磐戸町奇譚』の全素材の一覧と、その制作順。
このファイルは [`fields.json`](fields.json) から集計したものであり、**手で数えていない。**

```bash
python tools/aggregate_assets.py --project iwato            # 集計を再実行する
python tools/aggregate_assets.py --project iwato --format markdown
```

`fields.json` を更新したら集計を再実行し、この表を更新すること。

---

## 発注単位の考え方

**集計単位は「タイル1枚」ではなく「API の1コール」である。**

PixelLab の `/create-tileset` は**1コールで16タイルを返す**。下地形・上地形・境界の3つを指定すると、その組み合わせの接続パターンが一括で生成される。したがってタイル単位で数えると、コストも工数も実態から大きく外れる。

| 素材の種類 | エンドポイント | 1コールの産出 |
| --- | --- | --- |
| 地面（ground レイヤー） | `POST /create-tileset` | **16タイル** |
| 単体オブジェクト（objects / overhead） | `POST /map-objects` | 1点 |
| UI 部品 | `POST /generate-ui-v2` | サイズにより 1〜64点 |
| アイコン | `POST /generate-image-v2` | 32px なら**64点の候補** |

タイルセットの発注は、`fields.json` の `required_tiles` がそのまま対応する。

```json
{ "id": "tile_asphalt_grass", "lower": "asphalt", "upper": "dry_grass", "transition": "bare_soil" }
```

これが `lower_description` / `upper_description` / `transition_description` になる。実際に渡す英語表現は `fields.json` の `terrain_vocabulary` に定義済みで、表記ゆれが起きない。

---

## 集計サマリ

| 区分 | コール数 | 産出点数 | 出典 |
| --- | ---: | ---: | --- |
| タイルセット（ground） | 22 | **352** | `fields.json` |
| objects レイヤー | 91 | 91 | `fields.json` |
| overhead レイヤー | 14 | 14 | `fields.json` |
| UI 部品 | 12 | 12 | 本ファイル |
| アイコン | 16 | 16 | 本ファイル |
| **合計** | **155** | **485** | |

タイルセット22コールのうち **11 が共通**（2フィールド以上で使用）、11 がフィールド固有。共通率が高く、フィールドを増やしても線形にはコストが増えない構造になっている。

---

## 1. タイルセット（ground レイヤー）— 22 コール / 352 タイル

`lower` × `upper` × `transition` の組が1コール。使用数の多い順に並べてある。**上位から作れば手戻りが最小になる。**

| タイルセットID | 内容 | lower | upper | transition | 使用数 | 使用フィールド |
| --- | --- | --- | --- | --- | ---: | --- |
| `tile_soil_grass` | 土と伸びた雑草 | 乾いた地面 | 伸びきった夏草 | — | 8 | F04, F07, F09, F10, F12, F13, F14, F15 |
| `tile_asphalt_curb` | アスファルトと縁石・側溝 | ひび割れたアスファルト | 縁石と側溝・グレーチング | — | 7 | F01, F02, F05, F06, F11, F12, F13 |
| `tile_concrete_grass` | コンクリートと夏枯れの草 | コンクリート舗装 | 夏枯れのまだらな草 | — | 6 | F02, F05, F06, F11, F12, F13 |
| `tile_gravel_grass` | 砂利と夏枯れの草 | 締まった砂利 | 夏枯れのまだらな草 | — | 5 | F04, F07, F08, F10, F14 |
| `tile_forest_floor` | 林床と下草 | 杉の落葉が積もる林床 | 日陰の下草 | — | 3 | F04, F09, F16 |
| `tile_asphalt_grass` | アスファルトと夏枯れの草 | ひび割れたアスファルト | 夏枯れのまだらな草 | 乾いた地面 | 2 | F01, F03 |
| `tile_infield` | 夏枯れの芝と土のグラウンド | 夏枯れのまだらな草 | グラウンドの土 | — | 2 | F10, F11 |
| `tile_linoleum_wood` | リノリウムと板張り | 傷んだリノリウム床 | 黒ずんだ板の間 | — | 2 | F06, F11_1F |
| `tile_stone_moss` | 石畳と苔 | 踏み減った石畳 | 苔むした古い石 | — | 2 | F05, F07 |
| `tile_stone_steps` | 石段と苔 | 風化した石段 | 苔むした古い石 | 日陰の下草 | 2 | F08, F16 |
| `tile_wood_corridor` | 板張り廊下と教室床 | 黒ずんだ板の間 | 傷んだリノリウム床 | — | 2 | F11_1F, F11_2F |
| `tile_bridge_deck` | 橋面と伸縮継手 | 橋面と伸縮継手 | 縁石と側溝・グレーチング | — | 1 | F15 |
| `tile_concrete_slab` | コンクリート床とアスファルトの継ぎ | コンクリート舗装 | ひび割れたアスファルト | — | 1 | F03 |
| `tile_dead_orchard` | 枯れた梅林の地面 | 枯れた梅林の地面 | 夏枯れのまだらな草 | — | 1 | F08 |
| `tile_earthwork` | 草に覆われた土塁と空堀 | 草に覆われた土塁 | 落葉の溜まった空堀の底 | — | 1 | F09 |
| `tile_embankment` | 法面の草と法枠 | 刈られた法面の草 | 法枠コンクリート | — | 1 | F03 |
| `tile_gym_floor` | 体育館の床とライン | 黒ずんだ板の間 | 褪せた白線 | — | 1 | F11_GYM |
| `tile_paddy_ridge` | 水田と畦 | 水田の浅い水 | 畦 | — | 1 | F14 |
| `tile_parking_line` | 駐車場と白線 | 駐車場の平らな舗装 | 褪せた白線 | — | 1 | F01 |
| `tile_river_gravel` | 川面と河原の礫 | 浅く緩い川面 | 河原の礫 | — | 1 | F15 |
| `tile_ruin_stone` | 崩れた礎石と苔 | 崩れた礎石 | 苔むした古い石 | 日陰の下草 | 1 | F16 |
| `tile_tatami_wood` | 畳と板の間 | 擦れた畳 | 黒ずんだ板の間 | — | 1 | F02 |

`tile_soil_grass`（8フィールド）と `tile_asphalt_curb`（7フィールド）の2つで、16フィールド中13フィールドの地面の大半が埋まる。**この2つの品質が作品全体の印象を決める。**

---

## 2. objects レイヤー — 91 点

プレイヤーと同じ高さに描画される物。`/map-objects` で透過付きで生成する。

| 素材ID | 使用数 | 使用フィールド |
| --- | ---: | --- |
| `obj_utility_pole` | 12 | F01, F02, F03, F04, F05, F06, F10, F11, F12, F13, F14, F15 |
| `obj_wire_fence` | 6 | F04, F09, F10, F11, F14, F15 |
| `obj_stair_handrail` | 4 | F03, F08, F09, F11_2F |
| `obj_street_light_mercury` | 4 | F01, F05, F10, F15 |
| `obj_guardrail` | 3 | F01, F03, F15 |
| `obj_hedge` | 3 | F02, F07, F13 |
| `obj_irrigation_channel` | 3 | F04, F10, F14 |
| `obj_potted_plant` | 3 | F02, F05, F13 |
| `obj_signboard_pole` | 3 | F01, F09, F13 |
| `obj_stone_lantern` | 3 | F07, F08, F16 |
| `obj_stone_marker` | 3 | F09, F14, F16 |
| `obj_street_light_led` | 3 | F06, F12, F13 |
| `obj_traffic_cone` | 3 | F01, F03, F15 |
| `obj_vending_machine` | 3 | F01, F03, F06 |
| `obj_agricultural_machine` | 2 | F04, F14 |
| `obj_air_conditioner_outdoor` | 2 | F02, F12 |
| `obj_backstop` | 2 | F10, F11 |
| `obj_bench` | 2 | F06, F10 |
| `obj_bicycle` | 2 | F02, F05 |
| `obj_bicycle_rack` | 2 | F06, F12 |
| `obj_blackboard` | 2 | F11_1F, F11_2F |
| `obj_block_wall` | 2 | F02, F13 |
| `obj_bookshelf` | 2 | F06, F11_2F |
| `obj_bulletin_board` | 2 | F06, F12 |
| `obj_classroom_window` | 2 | F11_1F, F11_2F |
| `obj_corridor_door` | 2 | F11_1F, F11_2F |
| `obj_farm_shed` | 2 | F04, F14 |
| `obj_foundation_stone` | 2 | F07, F16 |
| `obj_kei_car` | 2 | F01, F13 |
| `obj_laundry_pole` | 2 | F02, F12 |
| `obj_mailbox` | 2 | F02, F13 |
| `obj_noise_barrier` | 2 | F03, F09 |
| `obj_offering_box` | 2 | F07, F08 |
| `obj_planter_box` | 2 | F06, F12 |
| `obj_river_marker` | 2 | F10, F15 |
| `obj_school_desk` | 2 | F11_1F, F11_2F |
| `obj_side_ditch_cover` | 2 | F05, F13 |
| `obj_stone_buddha` | 2 | F07, F16 |
| `obj_swing_set` | 2 | F11, F12 |
| `obj_temple_gate` | 2 | F05, F07 |
| `obj_torii` | 2 | F08, F14 |
| `obj_wall_clock` | 2 | F11_1F, F11_2F |
| `obj_water_basin` | 2 | F07, F08 |
| `obj_water_tank` | 2 | F02, F12 |
| `obj_bridge_pier` | 1 | F03 |
| `obj_bridge_railing` | 1 | F15 |
| `obj_bus_stop_pole` | 1 | F03 |
| `obj_cedar_trunk` | 1 | F16 |
| `obj_chestnut_tree` | 1 | F04 |
| `obj_civic_facade` | 1 | F06 |
| `obj_conveni_front` | 1 | F01 |
| `obj_danchi_facade` | 1 | F12 |
| `obj_electric_fan` | 1 | F02 |
| `obj_ema_rack` | 1 | F08 |
| `obj_fallen_log` | 1 | F16 |
| `obj_fire_extinguisher` | 1 | F11_1F |
| `obj_flag_pole` | 1 | F11 |
| `obj_folded_mat` | 1 | F11_GYM |
| `obj_goal_post` | 1 | F10 |
| `obj_grave_marker` | 1 | F07 |
| `obj_gym_facade` | 1 | F11 |
| `obj_gym_window_high` | 1 | F11_GYM |
| `obj_house_facade_newtown` | 1 | F13 |
| `obj_house_facade_showa` | 1 | F02 |
| `obj_komainu` | 1 | F08 |
| `obj_low_table` | 1 | F02 |
| `obj_ox_statue` | 1 | F08 |
| `obj_persimmon_tree` | 1 | F04 |
| `obj_plum_tree_bare` | 1 | F08 |
| `obj_police_box` | 1 | F06 |
| `obj_public_phone` | 1 | F06 |
| `obj_rice_plant_cluster` | 1 | F14 |
| `obj_road_closure_sign` | 1 | F15 |
| `obj_road_mirror` | 1 | F01 |
| `obj_room_interior_stopped` | 1 | F02 |
| `obj_school_gate` | 1 | F11 |
| `obj_shoe_locker` | 1 | F11_1F |
| `obj_shop_facade_roadside` | 1 | F01 |
| `obj_shop_facade_shutter` | 1 | F05 |
| `obj_shrine_facade` | 1 | F08 |
| `obj_shrine_small` | 1 | F14 |
| `obj_signboard_shutter` | 1 | F05 |
| `obj_stage_curtain` | 1 | F11_GYM |
| `obj_temple_bell` | 1 | F07 |
| `obj_tunnel_light` | 1 | F03 |
| `obj_upright_piano` | 1 | F11_GYM |
| `obj_vending_machine_old` | 1 | F05 |
| `obj_wall_bars` | 1 | F11_GYM |
| `obj_water_fountain` | 1 | F11 |
| `obj_wooden_hall_facade` | 1 | F07 |
| `obj_wooden_school_facade` | 1 | F11 |

---

## 3. overhead レイヤー — 14 点

プレイヤーより手前に描画される物。電線、庇、樹冠、天井。**「上に何かがある」ことが本作の不安の一部**（F03 の高架、F16 の樹冠）なので、点数は少ないが重要度は高い。

| 素材ID | 使用数 | 使用フィールド |
| --- | ---: | --- |
| `ovh_power_line` | 12 | F01, F02, F03, F04, F05, F06, F10, F11, F12, F13, F14, F15 |
| `ovh_tree_canopy_cedar` | 5 | F07, F08, F09, F14, F16 |
| `ovh_eaves_tile` | 3 | F02, F07, F08 |
| `ovh_ceiling_light_off` | 2 | F11_1F, F11_2F |
| `ovh_shop_awning` | 2 | F01, F05 |
| `ovh_tree_canopy_broadleaf` | 2 | F04, F11 |
| `ovh_viaduct_deck` | 2 | F03, F09 |
| `ovh_arcade_frame` | 1 | F05 |
| `ovh_balcony_danchi` | 1 | F12 |
| `ovh_building_eaves_flat` | 1 | F06 |
| `ovh_canopy_dense` | 1 | F16 |
| `ovh_ceiling_truss` | 1 | F11_GYM |
| `ovh_eaves_flat` | 1 | F13 |
| `ovh_eaves_wooden` | 1 | F11 |

---

## 4. UI 部品 — 12 点

`fields.json` には含まれない（フィールドに紐づかないため）。`/generate-ui-v2` で生成する。

| 素材ID | 内容 | 想定サイズ | 優先度 |
| --- | --- | --- | ---: |
| `ui_dialog_frame` | 会話ウィンドウの枠 | 304×72 | P2 |
| `ui_dialog_nameplate` | 話者名のプレート | 96×20 | P2 |
| `ui_text_cursor` | 次へ送る三角 | 8×8 | P2 |
| `ui_choice_cursor` | 選択肢のカーソル | 12×12 | P2 |
| `ui_menu_frame` | メニューの枠 | 200×160 | P3 |
| `ui_button` | ボタン（通常／押下） | 64×20 | P3 |
| `ui_scrollbar` | スクロールバー | 8×80 | P3 |
| `ui_item_slot` | 持ち物の枠 | 36×36 | P3 |
| `ui_notebook_frame` | 手帳（調査記録）の枠 | 288×176 | P3 |
| `ui_map_frame` | 町の地図画面の枠 | 320×200 | P3 |
| `ui_map_pin` | 現在地のピン | 12×12 | P3 |
| `ui_date_plate` | 日付表示（8月◯日） | 80×24 | P2 |

`ui_date_plate` は8月1日〜31日の日付進行を常時示すため、**画面に出ている時間が最も長い UI** である。優先度を上げてある。

---

## 5. アイコン — 16 点

アイテムと証拠。32×32。`/generate-image-v2` は32pxなら**1コールで64点の候補**を返すため、単価に対して選択肢が多い。

| 素材ID | 内容 |
| --- | --- |
| `icon_flashlight` | 懐中電灯（携帯できる唯一の光源） |
| `icon_battery` | 電池 |
| `icon_key` | 鍵 |
| `icon_notebook` | 手帳 |
| `icon_photo` | 写真 |
| `icon_letter` | 手紙 |
| `icon_newspaper_clip` | 新聞の切り抜き |
| `icon_map_paper` | 町の地図 |
| `icon_coin` | 小銭 |
| `icon_phone_card` | テレホンカード |
| `icon_omamori` | お守り |
| `icon_ema` | 絵馬 |
| `icon_cassette` | カセットテープ |
| `icon_school_badge` | 校章バッジ |
| `icon_bottle_drink` | ペットボトル飲料 |
| `icon_umbrella` | 傘 |

**血・刃物・薬品・縄状のもの、その他の自傷を想起させる物は一切含めない。** これは演出上の妥協ではなく、[`docs/CONVENTIONS.md`](../../../docs/CONVENTIONS.md) と `fields.json` の `content_constraints` に定めた制約である。

---

---

## 再編後の集計（生産計画に沿った作り方別）

```
========================================================================================
生産計画に沿った再集計（作り方別）
========================================================================================
区分                                 点数        コール        generations  状態
----------------------------------------------------------------------------------------
タイルセット A（地形ペア）                     15         45          135 - 180  実証済み
タイルセット（連続構造物）                       2          6            18 - 24  未検証
タイルセット B（平坦2素材）                     7         21            63 - 84  未検証
屋根タイルセット                            5         15            45 - 60  未検証
地面の装飾（ground_detail）                8         24            24 - 24  投影の影響なし
低い単体物（objects）                     50        150          150 - 150  未検証
overhead                           14         42            42 - 42  未検証
高い単体物（objects）                     16         48                 未定  **未解決**
他へ統合（単独では作らない）                      6          —                  —  統合済み
----------------------------------------------------------------------------------------
小計（作るもの・未解決を除く）                   101        303          477 - 564

  タイルセットから得られるタイル: 464 枚（1本16タイル）

  ※ UI とアイコンは fields.json に含まれない。ASSETS_NEEDED.md を参照。
  ※ 高い単体物 16 点は作り方が未解決のため見積もらない。
```

`python tools/aggregate_assets.py --project iwato --plan` で再生成できます。

### 契約枠との関係

| 項目 | 値 |
| --- | ---: |
| Tier 1 の月間枠 | **2,000 generations** |
| 作るもの（未解決を除く） | 477 〜 564 |
| 未解決16点をタイルセットで作った場合の追加 | 約 144 〜 192 |
| **合計の見込み** | **約 621 〜 756** |

**月間枠の3〜4割に収まります。枠は制約になりません。**
ただし無駄撃ちはしないこと。方針は変わりません。

### 未解決の規模 — 24点から16点へ絞り込みました

軸は **「真上から見たときに何が見えるか」** です。

| 移動先 | 点数 | 内容 |
| --- | ---: | --- |
| **overhead へ統合** | 4 | 葉のある樹木3点は**真上からは樹冠しか見えない**（幹は不要）。隧道の照明は天井付き |
| **タイルセット化** | 2 | 防音壁・バックネットは**連続する面**であり、1点の物ではない |
| **形状を統合** | 2 | 街灯（水銀灯／LED）と自販機（新／旧）は**形が同じで色だけが違う**。パレット置換で分けられる |
| **真に未解決** | **16** | 真上から見ても「立っている姿」を描く必要がある物 |

**`obj_utility_pole`（電柱）は12フィールドで使う最頻の素材**です。
これが解決すれば影響範囲の大部分が片付き、逆に**電柱1点の成否が量産の可否をほぼ決めます。**

---

## 優先度と制作順

**手戻りが最小になる順**に並べてある。上から順に作る。

### P0 — F06 パイロット（7点 / 画風の確定）

**これだけを先に作り、承認を得てから先へ進む。** 素材を揃えることが目的ではなく、**画風を確定すること**が目的である。

| 素材ID | 何を検証するか |
| --- | --- |
| `tile_concrete_grass` | 地面の基本。夏枯れの草の彩度と、コンクリートの褪せ具合 |
| `tile_asphalt_curb` | 側溝とグレーチング。日本の道路であることの記号 |
| `obj_vending_machine` | **最重要。** 彩度の高い光源が許される唯一の対象。光と影のコントラストの基準になる |
| `obj_street_light_led` | 青白い光源。自販機との色温度差 |
| `obj_civic_facade` | 建物。**真上見下ろしで高さをどう表現するか**の答えを出す |
| `obj_utility_pole` | 電柱。日本の地方都市であることの記号 |
| `ovh_power_line` | overhead レイヤーが成立するかの検証 |

7点 × 3〜4回の試行 = **21〜28コール**。タスク6の上限30枚に収まる。

### P1 — 共通タイルセット（11コール）

使用フィールド数2以上のタイルセット。**F06 の画風が承認されてから着手する。** ここを先に作ると、画風変更時の手戻りが最大になる。

### P2 — 高頻度オブジェクト（44点）＋ 主要 UI（5点）

2フィールド以上で使うオブジェクトと、画面に出ている時間が長い UI。

### P3 — フィールド固有タイルセット（11コール）＋ 単発オブジェクト（61点）＋ 残り UI（7点）＋ アイコン（16点）

### P4 — F11 旧校舎の屋内（タイルセット2 / オブジェクト16）

中核ダンジョン。屋外の画風が固まってから着手する。屋内は光源が窓のみで、屋外とは配色の設計が別になるため、**最後にまとめて作るほうが一貫する。**

---

## 総点数と推定コスト

### コール数の見積もり

| 区分 | 素材点数 | 試行回数 | コール数 |
| --- | ---: | ---: | ---: |
| タイルセット | 22 | ×3 | 66 |
| objects | 91 | ×3 | 273 |
| overhead | 14 | ×3 | 42 |
| UI | 12 | ×3 | 36 |
| アイコン | 16 | ×1.5 | 24 |
| 後処理（`/reduce-colors`, `/correct-pixelart`） | — | — | 約 90 |
| **合計** | **155** | | **約 531** |

アイコンの試行回数が少ないのは、1コールで64点の候補が返るため。後処理は採用点数のおおむね半分に対して呼ぶ想定。

### コスト概算

PixelLab は固定単価表を公開していない。**レスポンスの `usage.usd` が実額を返す**ため、確定値は実行後に報告する。以下は公表されている目安（1 generation ≈ $0.005、タイルセット1コール = 1〜4 generations、64px 画像1枚 = $0.007〜0.018）からの規模把握である。

| 区分 | 下限 | 上限 |
| --- | ---: | ---: |
| タイルセット（66コール） | $0.99 | $1.32 |
| objects + overhead（315コール） | $3.15 | $6.30 |
| UI（36コール） | $0.36 | $1.08 |
| アイコン（24コール） | $0.12 | $0.24 |
| 後処理（約90コール） | $0.45 | $0.90 |
| **合計** | **約 $5.1** | **約 $9.8** |

**16フィールド全体で $10 前後。** 円換算で1,500円程度である。

この見積もりが小さいのは、`/create-tileset` が1コールで16タイルを返すためである。**352タイルのうち、実際の API コールは66回**（試行込み）にすぎない。

---

## 削減案

**予算は制約にならない**ため、コスト削減のための削減は行わない。以下は**重複の解消**であり、点数を減らすこと自体が目的ではない。

| 対象 | 提案 | 削減 |
| --- | --- | --- |
| `ovh_eaves_flat`（F13）と `ovh_building_eaves_flat`（F06） | 実質同じ「陸屋根の庇」。`ovh_eaves_flat` に統合する | −1 |
| `obj_bicycle`（F02, F05）と `obj_bicycle_rack`（F06, F12） | 駐輪ラックに自転車が差さった1点にまとめられる | −1 |
| `obj_potted_plant`（F02, F05, F13）と `obj_planter_box`（F06, F12） | 私有の鉢植えと公共のプランターは別物。**統合しない** | 0 |
| `obj_street_light_mercury` と `obj_street_light_led` | **統合しない。** 水銀灯のナトリウム橙と LED の青白は、本作の光源設計そのものである | 0 |

統合による削減は **2点**（485 → 483）。誤差である。**この規模では、統合の手間のほうが高くつく。**

一方、**増やすべきでないもの**についても明記しておく。

- **時間帯差分を素材として発注しないこと。** 下記のとおりパレット置換で作る。
- **ノーマルマップを API で発注しないこと。** ローカル生成する。
- **同じ物の色違いを別素材にしないこと。** パレット置換で足りる。

これらを守らないと、485点は容易に3倍に膨れる。

---

## 時間帯差分の扱い（重要）

`fields.json` の各フィールドに `time_variants`（朝／昼／夕／夜）を持たせてあるが、**これは API の再生成対象ではない。**

時間帯の色調変化は、**確定した64色パレット内での色置換テーブル**で表現する。`tools/postprocess.py` にパレット適用の機構があるため、同じ仕組みで「昼→夜」の対応表を持たせればよい。

- **API コストは 0** である
- 全素材の時間帯差分が**機械的に一貫する**（手で塗り直すとフィールドごとにばらつく）
- パレットを直せば全時間帯に一括で反映される

これを API で作ると、485点 × 3時間帯 = 1,455点となり、コストも一貫性も破綻する。

---

## ノーマルマップ

2Dライト用のノーマルマップは `tools/normalmap.py` で**ローカル生成する。API は使わない。**

対象は地面と大きなオブジェクト（タイルセット352枚 + objects 91点 = 443点）。UI とアイコンには不要。

> Godot では法線の **Y 軸を反転する**必要がある。詳細はタスク5で `docs/` に記載する。

---

## 未決事項

- ~~`objects` / `overhead` の置き場所が未定~~ → **解決済み。** `asset_categories` を `[tilesets, objects, overhead, ui, icons]` とし、Godot のレイヤー構成と1対1で対応させた。
- ~~`backgrounds` カテゴリの用途が未確定~~ → **解決済み。** タイルセットで地面を組む方式のため1枚絵の背景は0点であり、削除した。タイトル画面などが必要になった時点で `screens` カテゴリを新設する。
- UI とアイコンの一覧は本ファイルにのみ存在し、`fields.json` に無い。シナリオが固まった時点でアイコンは増減する。
- 後処理のコール数（約90）は概算。`/reduce-colors` をローカルの Pillow 実装で代替できれば 0 にできる。**タスク5で判断する。**
