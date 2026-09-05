extends Node2D
## 納品済みの素材に 2Dライトとノーマルマップを乗せ、見え方を確かめる。
##
## **ゲーム本体ではない。** 素材リポジトリの assets/ を直接読む。
## 作り直しは一切しない。
##
##   1..4     時間帯（朝・昼・夕・夜）
##   Q W E R  段階 0〜3（後述）
##   L        ライトの入切
##   N        ノーマルマップの入切
##   S        スクリーンショット（user:// へ保存）
##
## 時間帯は **CanvasModulate の色調**で作る。パレット置換（時間帯ごとに
## 色を差し替える設計）は本来シェーダで行うが、ここでは見え方の確認が
## 目的なので色調の乗算で近似している。**この違いは報告に明記する。**
##
## ---------------------------------------------------------------------
## **段階（`_stage`）。何がどれだけ効いたかを切り分けるためにある。**
##
##   0  光と法線だけ。**落ち影なし、シェーダなし**（最初に見せた状態）
##   1  ＋ 落ち影。LightOccluder2D と接地の陰り。**まだシェーダなし**
##   2  ＋ 立ち物の法線を「形から起こしたもの」へ差し替え。**まだシェーダなし**
##   3  ＋ シェーダ3種（減衰カーブ／濡れた路面の映り込み／ブルーム）
##
## **0〜2 はシェーダを1行も使っていない。** 素材と Godot 標準のノードだけ。
## 3 で初めてシェーダが入る。どこからが後処理かを区別できるようにしてある。

const ASSETS := "res://assets"
const TILE := 32
const W := 30
const H := 14

## 受光の層。**地面は影を受け、立ち物は受けない。**
##   真上見下ろしの画面では、影は地面に落ちる。立ち物どうしが互いの影で
##   暗くなると、**何が置いてあるか読めなくなる**（32px では致命的である）。
## 影の色。**黒ではなく藍。** 参考画像の「暖色の光 対 寒色の影」の、寒色側。
##
## 最初は乗算（`BLEND_MODE_MUL`）で置いた。地面の色を保ったまま暗くできる
## から筋は良い。**が、この環境では乗算がテクスチャの色を無視して効いた。**
## 真っ白なテクスチャに差し替えても暗さが変わらなかった（実測で確認した）。
## **挙動を説明できないものに頼らない。** 通常のアルファ合成に戻し、
## 濃さは撮った画素を測って決めた。
const SHADOW_RGB := Color(0.05, 0.06, 0.13)

const MASK_GROUND := 1
const MASK_OBJECT := 2

var _time_index := 3          # 既定は夜。**本作の核となる絵**
var _lights_on := true
var _normals_on := true
var _stage := 3
var _height_scale := 1.0
## 落ち影の作り方。**2つある。切り分けて見られるようにしてある。**
##   1 遮蔽（LightOccluder2D）  2 形の投影  4 接地の陰り  7 すべて
var _shadow_mode := 7

var _ground := Node2D.new()
var _shadows := Node2D.new()       # 接地の陰り。地面と物の間に置く
var _objects := Node2D.new()
var _occluders := Node2D.new()
var _light_root := Node2D.new()
var _modulate := CanvasModulate.new()
var _label := Label.new()
var _post_layers: Array = []       # シェーダ（段階3でだけ作る）

## 時間帯ごとの全体色調。**夜は藍へ大きく沈める。**
const TINTS := {
	0: Color(0.72, 0.76, 0.86),   # 朝  湿って青い
	1: Color(1.00, 1.00, 1.00),   # 昼  基準
	2: Color(0.66, 0.55, 0.52),   # 夕  光が弱り土へ寄る
	3: Color(0.20, 0.24, 0.40),   # 夜  藍へ沈む
}
const TIME_NAMES := ["朝", "昼", "夕", "夜"]

## 灯りの入り方は時間帯で変わる。**昼に街灯は点かない。**
## 色調だけでなく**灯りの強さも時間帯の一部**である（第23節）。
const LIGHT_GAIN := {0: 0.35, 1: 0.0, 2: 0.55, 3: 1.0}   # 人工光
const MOON_GAIN := {0: 0.25, 1: 0.0, 2: 0.45, 3: 1.0}    # 月光

## にじみの強さ。**夜だけ強い。**
const BLOOM_GAIN := {0: 0.28, 1: 0.10, 2: 0.34, 3: 0.50}

## **太陽。** 点光源ではなく平行光なので、Light2D では作らない。
## 明るさは素材と色調がすでに持っている。**太陽から要るのは影だけ**である。
##   dir …… 影の伸びる向き（画面座標）  len …… 物の高さに対する影の長さ
## 朝と夕は低いので長く、真昼は高いので短い。**夜は無い。**
const SUN := {
	0: {"dir": Vector2(0.86, 0.51), "len": 1.05, "a": 0.50},   # 朝  東から
	1: {"dir": Vector2(0.22, 0.98), "len": 0.38, "a": 0.52},   # 昼  ほぼ真上
	2: {"dir": Vector2(-0.90, 0.44), "len": 1.20, "a": 0.52},  # 夕  西から
}

## 光源。位置・色・強さ・広がり・**高さ（画素）**。
##   height は法線の効きを決める。既定の 0 では平らな面への入射角が 90 度に
##   なって何も照らされない。**単位は画素**（第22節）。
const LIGHTS := [
	# 自販機の発光面。**白緑。本作で最も彩度が許される色**
	{"pos": Vector2(7 * 32 + 16, 8 * 32 - 40), "col": Color(0.30, 0.78, 0.68),
	 "energy": 1.5, "scale": 1.1, "height": 24.0, "moon": false},
	# 街灯。水銀灯はナトリウム橙
	{"pos": Vector2(11 * 32 + 16, 8 * 32 - 96), "col": Color(0.78, 0.50, 0.18),
	 "energy": 1.7, "scale": 1.6, "height": 48.0, "moon": false},
	# LED は青白
	{"pos": Vector2(20 * 32 + 16, 8 * 32 - 96), "col": Color(0.53, 0.69, 0.71),
	 "energy": 1.5, "scale": 1.5, "height": 48.0, "moon": false},
	# 月光。広く弱く、蒼白。**影は落とさない**（空全体が光る面光源であり、
	# 一点から出る光ではない。輪郭のはっきりした影は落ちない）
	{"pos": Vector2(W * 32 * 0.5, H * 32 * 0.35), "col": Color(0.34, 0.40, 0.58),
	 "energy": 0.55, "scale": 5.0, "height": 96.0, "moon": true},
]


func _ready() -> void:
	add_child(_ground)
	add_child(_shadows)
	add_child(_objects)
	add_child(_occluders)
	add_child(_light_root)
	add_child(_modulate)
	_build_hud()
	var auto := ""
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--stage="):
			_stage = int(a.split("=")[1])
		if a.begins_with("--height="):
			_height_scale = float(a.split("=")[1])
		if a.begins_with("--shadow="):
			_shadow_mode = int(a.split("=")[1])
		if a == "--sweep" or a == "--auto" or a == "--stages" or a == "--shadows":
			auto = a
	_build_all()
	if auto != "":
		_label.visible = false
		call_deferred("_" + auto.substr(2) + ("_" if auto == "--shadows" else ""))


func _build_all() -> void:
	_build_ground()
	_build_objects()
	_build_lights()
	_build_post()
	_apply_time()


## --- 地面 -----------------------------------------------------------------
## タイルは **スーパータイルの並び順どおり**に置く。ランダムに置くと
## 連続性が壊れる（PILOT_FINDINGS 第13節）。
func _tile_texture(set_name: String, kind: String, cx: int, ny: int, nx: int) -> Texture2D:
	var idx := (ny % nx) * nx + (cx % nx)
	var path := "%s/tilesets/%s/super_%s_%02d.png" % [ASSETS, set_name, kind, idx]
	if not ResourceLoader.exists(path):
		path = "%s/tilesets/%s/alt_%s_%02d.png" % [ASSETS, set_name, kind, cx % 12]
	if not ResourceLoader.exists(path):
		path = "%s/tilesets/%s/wang_%d.png" % [ASSETS, set_name, 0 if kind == "lower" else 15]
	return load(path)


## 素材と法線を束ねる。`suffix` で **どの法線を使うか**を選ぶ。
##   "_n" 輝度から起こしたもの（地面用）
##   "_s" 形から起こしたもの（立ち物用。段階2以降）
func _skin(tex: Texture2D, suffix: String) -> Texture2D:
	if not _normals_on or tex == null:
		return tex
	var n_path: String = tex.resource_path.get_basename() + suffix + ".png"
	if not ResourceLoader.exists(n_path):
		n_path = tex.resource_path.get_basename() + "_n.png"
	if not ResourceLoader.exists(n_path):
		return tex
	var ct := CanvasTexture.new()
	ct.diffuse_texture = tex
	ct.normal_texture = load(n_path)
	return ct


func _put(tex: Texture2D, x: int, y: int, parent: Node2D,
		suffix: String = "_n", mask: int = MASK_GROUND) -> void:
	if tex == null:
		return
	var s := Sprite2D.new()
	s.texture = _skin(tex, suffix)
	s.centered = false
	s.position = Vector2(x, y)
	s.light_mask = mask
	parent.add_child(s)


func _build_ground() -> void:
	# 草地（0-4） / 歩道（5-8） / 車道（9-）の3帯。F01 国道沿いを想定する。
	for cy in range(H):
		for cx in range(W):
			var tex: Texture2D
			if cy <= 4:
				tex = _tile_texture("tile_soil_grass", "upper", cx, cy, 8)
			elif cy <= 8:
				tex = _tile_texture("tile_asphalt_curb", "upper", cx, cy, 1)
			else:
				tex = _tile_texture("tile_asphalt_curb", "lower", cx, cy, 1)
			_put(tex, cx * TILE, cy * TILE, _ground)
	# 縁石。歩道と車道の境（Wang タイル）
	var curb := load("%s/tilesets/tile_asphalt_curb/wang_12.png" % ASSETS)
	for cx in range(W):
		_put(curb, cx * TILE, 8 * TILE, _ground)
	# 路面標示とマンホール
	for cx in [4, 8, 12, 16]:
		_put(load("%s/deco/deco_road_marking.png" % ASSETS), cx * TILE, 11 * TILE, _ground)
	_put(load("%s/deco/deco_manhole.png" % ASSETS), 22 * TILE, 12 * TILE, _ground)


## --- 物 -------------------------------------------------------------------
const PLACEMENT := [
	["obj_utility_pole", 2, 8],
	["obj_utility_pole", 15, 8],
	["obj_utility_pole", 26, 8],
	["obj_vending_machine", 7, 8],
	["obj_street_light_mercury", 11, 8],
	["obj_street_light_led", 20, 8],
	["obj_bench", 17, 8],
	["obj_guardrail", 23, 8],
	["obj_traffic_cone", 12, 12],
	["obj_kei_car", 5, 12],
]


func _build_objects() -> void:
	for entry in PLACEMENT:
		var path := "%s/objects/%s.png" % [ASSETS, entry[0]]
		if not ResourceLoader.exists(path):
			continue
		var tex: Texture2D = load(path)
		var foot := Vector2(entry[1] * TILE, entry[2] * TILE)
		# **足元を基準に置く。** 立ち物は側面で描かれているので、
		# 画像の下端が接地点になる（第19節）。
		var suffix := "_s" if _stage >= 2 else "_n"
		_put(tex, int(foot.x), int(foot.y) - tex.get_height(), _objects, suffix, MASK_OBJECT)
		if _stage >= 1:
			var span := _footprint(tex)
			if _shadow_mode & 4:
				_add_contact_shadow(foot, span)
			if _shadow_mode & 1:
				_add_occluder(foot, span)
			if _shadow_mode & 2:
				_add_cast_shadows(tex, foot, span)


## 画像の下 6 行を見て、接地している幅（左端・右端）を返す。
## **物の見かけの幅ではなく、地面に着いている幅**である。電柱は細く、
## ガードレールは広い。これが影の根元の幅になる。
func _footprint(tex: Texture2D) -> Vector2:
	var img := tex.get_image()
	var lo := img.get_width()
	var hi := -1
	for y in range(max(0, img.get_height() - 6), img.get_height()):
		for x in range(img.get_width()):
			if img.get_pixel(x, y).a > 0.0:
				lo = min(lo, x)
				hi = max(hi, x)
	if hi < 0:
		return Vector2(0, tex.get_width())
	return Vector2(lo, hi + 1)


## --- 落ち影 ---------------------------------------------------------------
## **段階1。ここが一番効く。**
##
## 前の版では、自販機も街灯も電柱も地面に影を落としていなかった。
## 光の円が地面に描かれているだけで、遮蔽が無い。**物が浮いて見える。**
##
## 影は2種類ある。混同しないこと。
##   落ち影      光源の反対側へ伸びる。LightOccluder2D が作る。光ごとに向きが違う
##   接地の陰り  物の真下の暗がり。**光が無くても在る。** 環境光の遮蔽である
##
## 落ち影だけでは足りない。光の届かない物（画面端の電柱）が浮いたままになる。
func _add_occluder(foot: Vector2, span: Vector2) -> void:
	var occ := LightOccluder2D.new()
	var poly := OccluderPolygon2D.new()
	poly.closed = true
	poly.cull_mode = OccluderPolygon2D.CULL_DISABLED
	# **足元の帯だけを遮蔽体にする。** 立ち物の全身を遮蔽体にすると、
	# 側面で描かれた背丈がそのまま地面の穴になり、影が不自然に太る。
	poly.polygon = PackedVector2Array([
		Vector2(span.x, -3.0), Vector2(span.y, -3.0),
		Vector2(span.y, 2.0), Vector2(span.x, 2.0)])
	occ.occluder = poly
	occ.position = foot
	# **`light_mask` ではない。** LightOccluder2D は CanvasItem を継承するので
	# `light_mask` も持っており、代入しても何も言われない。**が、影には効かない。**
	# 遮蔽の対象を決めるのは `occluder_light_mask` である。
	# これを間違えたまま撮って、「遮蔽は効かない」と結論しかけた。
	occ.occluder_light_mask = MASK_GROUND
	_occluders.add_child(occ)


func _add_contact_shadow(foot: Vector2, span: Vector2) -> void:
	var s := Sprite2D.new()
	s.texture = _ellipse_texture()
	s.centered = true
	# **小さく、薄く。** 接地の陰りは足元の暗がりであって、物の下に敷く布ではない。
	# 最初は幅 1.6 倍・高さ 0.34 倍で作り、自販機の下に**黒い帯**ができた。
	var width: float = max(span.y - span.x, 6.0) * 0.90
	s.position = foot + Vector2((span.x + span.y) * 0.5, -2.0)
	s.scale = Vector2(width / 64.0, width / 64.0 * 0.20)
	s.modulate = Color(SHADOW_RGB.r, SHADOW_RGB.g, SHADOW_RGB.b, 0.62)
	s.light_mask = 0            # **光を受けない。** 遮蔽は光の有無と無関係
	_shadows.add_child(s)


## **形の投影による落ち影。**
##
## LightOccluder2D は「光を遮る板」を平面図として置く仕組みであり、
## **真上見下ろしの平面図には正しい。** ところがこのプロジェクトの立ち物は
## 側面で描かれている（第19節）。足元に遮蔽体を置くと、影は
## **光の反対側へ伸びる長方形**になり、電柱の影も自販機の影も同じ形になる。
## 実際に撮ったら、地面に黒い長方形が空いた。**遮蔽だけでは形が出ない。**
##
## そこで、**物のシルエットそのものを地面へ寝かせる。**
##   足元を固定し、物の天辺を「光の反対方向」へ倒す
##   遠い側ほど薄くする（焼き込んだ階調で作る。シェーダは使わない）
## 電柱は細長い影、ガードレールは横長の影、自販機は角ばった影になる。
##
## **この2つは競合しない。** 遮蔽は「光がそこへ届かない」ことを、
## 投影は「物の形」を担当する。両方あってはじめて参考画像に近づく。
func _add_cast_shadows(tex: Texture2D, foot: Vector2, span: Vector2) -> void:
	var lit := []
	# **太陽の影。** 昼の画面が浮いて見えたのはこれが無かったからである。
	# 参考画像（自作ゲーム）の力の大半は、低い太陽が落とす長い影にある。
	if SUN.has(_time_index):
		var sun: Dictionary = SUN[_time_index]
		lit.append({"a": float(sun["a"]), "dir": (sun["dir"] as Vector2).normalized(),
			"k": float(sun["len"])})
	# **人工光の影。** 昼は点いていないので落ちない（第23節）。
	var gain: float = LIGHT_GAIN[_time_index]
	for spec in LIGHTS:
		if spec["moon"] or gain <= 0.0:
			continue                       # 月光は面光源。輪郭のある影を落とさない
		var to: Vector2 = foot - spec["pos"]
		var reach: float = 128.0 * float(spec["scale"])
		var w: float = float(spec["energy"]) * gain 			* pow(clampf(1.0 - to.length() / reach, 0.0, 1.0), 1.4)
		if w > 0.05:
			lit.append({"a": clampf(w * 0.62, 0.0, 0.72),
				"dir": to.normalized(),
				"k": clampf(to.length() / (float(spec["height"]) * 4.5), 0.25, 0.90)})
	if lit.is_empty():
		return
	lit.sort_custom(func(a, b): return a["a"] > b["a"])
	# **多くても2灯まで。** 3灯ぶん重ねると足元が影だらけになって読めない。
	# **多くても2つまで。** 3つ重ねると足元が影だらけになって読めない。
	for i in range(min(2, lit.size())):
		var e: Dictionary = lit[i]
		var h := float(tex.get_height())
		var cx: float = (span.x + span.y) * 0.5
		var dir: Vector2 = e["dir"]
		# 影の長さ。**光が低いほど、遠いほど長い。**
		# ただし**長くしすぎないこと。** 物理どおりに伸ばすと 4m の電柱の影が
		# 画面の高さを超える。640x360 で読める長さに収める。
		var k: float = float(e["k"])
		var s := Sprite2D.new()
		var strength: float = float(e["a"]) * (0.55 if i else 1.0)
		s.texture = _silhouette_texture(tex)
		s.centered = false
		s.transform = Transform2D(Vector2(1, 0), -dir * k, foot - Vector2(cx, 0) + dir * k * h)
		s.offset = Vector2(cx, 0)
		s.modulate = Color(SHADOW_RGB.r, SHADOW_RGB.g, SHADOW_RGB.b, strength)
		s.light_mask = 0
		_shadows.add_child(s)


var _silhouette_cache := {}


## シルエットを、**階調つきの影**に焼き直す。
## アルファだけを使う。**天辺（＝影の遠い端）ほど薄い。**
func _silhouette_texture(tex: Texture2D) -> Texture2D:
	var key: String = tex.resource_path
	if _silhouette_cache.has(key):
		return _silhouette_cache[key]
	var src := tex.get_image()
	var w := src.get_width()
	var h := src.get_height()
	var img := Image.create(w, h, false, Image.FORMAT_RGBA8)
	for y in range(h):
		# **遠い端ほど薄い。** 影は物から離れるほどぼやけて消える。
		var t: float = float(y) / float(max(h - 1, 1))
		var a: float = lerp(0.28, 1.0, pow(t, 0.8))
		for x in range(w):
			img.set_pixel(x, y, Color(1, 1, 1, a if src.get_pixel(x, y).a > 0.5 else 0.0))
	_silhouette_cache[key] = ImageTexture.create_from_image(img)
	return _silhouette_cache[key]


var _ellipse_cache: Texture2D


func _ellipse_texture() -> Texture2D:
	if _ellipse_cache:
		return _ellipse_cache
	var size := 64
	var img := Image.create(size, size, false, Image.FORMAT_RGBA8)
	var c := size * 0.5
	for y in range(size):
		for x in range(size):
			var d: float = Vector2(x - c + 0.5, y - c + 0.5).length() / c
			img.set_pixel(x, y, Color(1, 1, 1, pow(clampf(1.0 - d, 0.0, 1.0), 2.2)))
	_ellipse_cache = ImageTexture.create_from_image(img)
	return _ellipse_cache


## --- 光 -------------------------------------------------------------------
## **暗さと受光面は実行時に作る**（第5節）。素材には焼き込まない。
##
## 光源ひとつにつき **PointLight2D を2つ**置く。
##   地面用   影を落とす。range_item_cull_mask = 地面
##   立ち物用 影を落とさない。range_item_cull_mask = 立ち物
## こうしないと、遮蔽体が自分の立っている物を暗くする。
func _build_lights() -> void:
	for spec in LIGHTS:
		var shadow: bool = _stage >= 1 and not spec["moon"]
		_add_light(spec, MASK_GROUND, shadow)
		_add_light(spec, MASK_OBJECT, false)


func _add_light(spec: Dictionary, mask: int, shadow: bool) -> void:
	var l := PointLight2D.new()
	l.texture = _radial_texture()
	l.position = spec["pos"]
	l.color = spec["col"]
	l.energy = spec["energy"]
	l.texture_scale = spec["scale"]
	l.height = float(spec["height"]) * _height_scale
	l.blend_mode = Light2D.BLEND_MODE_ADD
	l.range_item_cull_mask = mask
	l.shadow_enabled = shadow
	if shadow:
		l.shadow_item_cull_mask = MASK_GROUND
		l.shadow_filter = Light2D.SHADOW_FILTER_PCF13
		l.shadow_filter_smooth = 3.0
		# **影は黒で塗らない。** 加算ライトの影なので、ここで指定するのは
		# 「影の中で、その光が代わりに落とす分」である。**藍を薄く残す。**
		# **黒に近づけないこと。** 0.90 で撮ったら、自販機の後ろが
		# 「地面に空いた黒い長方形」になった。遮蔽は暗さであって穴ではない。
		l.shadow_color = Color(0.08, 0.09, 0.17, 0.68)
	l.set_meta("base_energy", spec["energy"])
	l.set_meta("moon", spec["moon"])
	_light_root.add_child(l)


var _radial_cache := {}


## 減衰カーブ。**段階3で自然な落ち方へ差し替える。**
##   0〜2  二乗。中心から一様に落ちる。**円がそのまま見える**
##   3     芯を持たせ、裾を長く引く。遠くまで薄く届く
func _radial_texture() -> Texture2D:
	var key := _stage >= 3
	if _radial_cache.has(key):
		return _radial_cache[key]
	var size := 256
	var img := Image.create(size, size, false, Image.FORMAT_RGBA8)
	var c := size * 0.5
	for y in range(size):
		for x in range(size):
			var d: float = Vector2(x - c, y - c).length() / c
			var t: float = clampf(1.0 - d, 0.0, 1.0)
			var a: float = pow(t, 2.0)
			if key:
				a = pow(t, 2.6) * 0.72 + pow(t, 1.15) * 0.28
			img.set_pixel(x, y, Color(1, 1, 1, a))
	_radial_cache[key] = ImageTexture.create_from_image(img)
	return _radial_cache[key]


## --- シェーダ（段階3だけ） -------------------------------------------------
## **ここから先は後処理である。素材の力ではない。**
const WET_SHADER := "
shader_type canvas_item;
// 濡れたアスファルトの映り込み。**車道の帯にだけ掛ける。**
// 上（歩道側）の画面を折り返し、横に揺らして薄く重ねる。
// 8月の夜、雨上がりの路面という設定である。
uniform sampler2D screen_tex : hint_screen_texture, filter_linear;
uniform float horizon;
uniform float strength = 0.55;

float hash(float p) { return fract(sin(p * 41.7) * 43758.5453); }

void fragment() {
	float depth = SCREEN_UV.y - horizon;
	// **手前ほど強く揺れる。** 実際の水膜がそう見える。
	float row = floor(SCREEN_UV.y / SCREEN_PIXEL_SIZE.y);
	float wobble = (hash(row) - 0.5) * depth * 0.10;
	vec2 uv = vec2(SCREEN_UV.x + wobble, horizon - depth * 0.92);
	vec3 refl = texture(screen_tex, clamp(uv, vec2(0.001), vec2(0.999))).rgb;
	// 暗い所は映さない。**映るのは光だけ。**
	float bright = max(refl.r, max(refl.g, refl.b));
	float k = smoothstep(0.16, 0.60, bright) * strength / (1.0 + depth * 6.0);
	COLOR = vec4(refl, clamp(k, 0.0, 1.0));
}
"

const BLOOM_SHADER := "
shader_type canvas_item;
// ブルーム。**明るい所だけを抜き出し、にじませて加算する。**
// ミップマップに頼らず固定の12方向を2つの半径で拾う（互換レンダラでも動く）。
uniform sampler2D screen_tex : hint_screen_texture, filter_linear;
uniform float threshold = 0.62;
uniform float amount = 0.45;

vec3 bright_at(vec2 uv) {
	vec3 c = texture(screen_tex, clamp(uv, vec2(0.0), vec2(1.0))).rgb;
	float l = max(c.r, max(c.g, c.b));
	return c * smoothstep(threshold, threshold + 0.30, l);
}

void fragment() {
	vec3 base = texture(screen_tex, SCREEN_UV).rgb;
	vec2 px = SCREEN_PIXEL_SIZE;
	vec3 sum = vec3(0.0);
	for (int i = 0; i < 12; i++) {
		float a = float(i) * 0.5236;
		vec2 dir = vec2(cos(a), sin(a));
		sum += bright_at(SCREEN_UV + dir * px * 3.0) * 0.62;
		sum += bright_at(SCREEN_UV + dir * px * 9.0) * 0.38;
	}
	sum /= 12.0;
	COLOR = vec4(base + sum * amount, 1.0);
}
"


func _post_rect(code: String, layer_index: int, pos: Vector2, size: Vector2,
		params: Dictionary) -> void:
	var layer := CanvasLayer.new()
	layer.layer = layer_index
	var rect := ColorRect.new()
	var mat := ShaderMaterial.new()
	var shader := Shader.new()
	shader.code = code
	mat.shader = shader
	for k in params:
		mat.set_shader_parameter(k, params[k])
	rect.material = mat
	rect.position = pos
	rect.size = size
	layer.add_child(rect)
	add_child(layer)
	_post_layers.append(layer)


func _build_post() -> void:
	for layer in _post_layers:
		if is_instance_valid(layer):
			layer.queue_free()
	_post_layers.clear()
	if _stage < 3:
		return
	# 映り込みは**地面と物の上、ブルームの下**。CanvasLayer の層で決める。
	_post_rect(WET_SHADER, 1, Vector2(0, 9 * TILE), Vector2(640, 360 - 9 * TILE),
		{"horizon": 9.0 * TILE / 360.0, "strength": 0.42})
	# **にじみは暗い場面でだけ強く出す。** 目の順応に相当する。
	# 一律に掛けたら、真昼の自販機の見本窓が**白く光る箱**になった。
	_post_rect(BLOOM_SHADER, 2, Vector2.ZERO, Vector2(640, 360),
		{"amount": BLOOM_GAIN[_time_index]})


## --- 表示 -----------------------------------------------------------------
func _build_hud() -> void:
	_label.position = Vector2(4, 2)
	_label.add_theme_font_size_override("font_size", 8)
	_label.add_theme_color_override("font_color", Color(0.9, 0.9, 0.95))
	_label.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.8))
	_label.add_theme_constant_override("shadow_offset_y", 1)
	var layer := CanvasLayer.new()
	layer.layer = 3
	layer.add_child(_label)
	add_child(layer)


func _apply_time() -> void:
	# **色調は光の入切と独立**。消灯した夜は「真っ暗な夜」であって昼ではない。
	_modulate.color = TINTS[_time_index]
	_light_root.visible = _lights_on
	for child in _light_root.get_children():
		var l := child as PointLight2D
		var gain: float = MOON_GAIN[_time_index] if l.get_meta("moon") else LIGHT_GAIN[_time_index]
		l.energy = float(l.get_meta("base_energy")) * gain
	_label.text = "%s  段階%d  ライト:%s  ノーマル:%s" % [
		TIME_NAMES[_time_index], _stage,
		"入" if _lights_on else "切", "入" if _normals_on else "切"]


func _unhandled_input(event: InputEvent) -> void:
	if not (event is InputEventKey and event.pressed and not event.echo):
		return
	match event.keycode:
		KEY_1, KEY_2, KEY_3, KEY_4:
			_time_index = event.keycode - KEY_1
			_rebuild()          # **太陽の向きが変わるので影も作り直す**
		KEY_Q, KEY_W, KEY_E, KEY_R:
			_stage = event.keycode - KEY_Q
			_rebuild()
		KEY_L:
			_lights_on = not _lights_on
			_apply_time()
		KEY_N:
			_normals_on = not _normals_on
			_rebuild()
		KEY_S:
			_shoot()
		KEY_ESCAPE:
			get_tree().quit()


func _rebuild() -> void:
	for parent in [_ground, _objects, _shadows, _occluders, _light_root]:
		for child in parent.get_children():
			parent.remove_child(child)
			child.queue_free()
	await get_tree().process_frame
	_build_all()


func _settle() -> void:
	await RenderingServer.frame_post_draw
	await get_tree().process_frame
	await RenderingServer.frame_post_draw


func _save(name: String) -> void:
	await _settle()
	var img := get_viewport().get_texture().get_image()
	img.save_png("user://%s.png" % name)
	print("保存: ", name)


## 比較に要る絵を順に撮る。**同じ構図で、条件だけを変える。**
func _auto() -> void:
	# [時間帯, ライト, ノーマル, 段階, 名前]
	var shots := [
		# **納品物そのもの。** 影も光もシェーダも無い、素材を並べただけの絵。
		[1, false, true, 0, "00_material"],
		# **昼は素材そのものが画面である。** 街灯も自販機も点かないので、
		# 昼に効くのは太陽の影だけ（第23節）。
		[1, false, true, 3, "01_daylight"],
		[0, true, true, 3, "03_morning"],
		[2, true, true, 3, "04_dusk"],
		[3, true, true, 3, "05_night"],             # **本作の核**
		[3, true, false, 3, "06_night_no_normal"],  # ノーマルマップの効きを見る
		[3, false, true, 3, "07_night_no_light"],
	]
	for shot in shots:
		_time_index = shot[0]
		_lights_on = shot[1]
		_normals_on = shot[2]
		_stage = shot[3]
		await _rebuild()        # **時間帯ごとに影を作り直す**
		await _save(shot[4])
	get_tree().quit()


## **段階ごとに1枚ずつ撮る。** どの要素が効いたかを見るための絵。
func _stages() -> void:
	_time_index = 3
	_lights_on = true
	_normals_on = true
	for st in [0, 1, 2, 3]:
		_stage = st
		await _rebuild()
		await _save("stage_%d" % st)
	# 夕方も撮る。**落ち影は夜より夕方のほうがよく見える**（光が斜めから来る）
	_stage = 3
	_time_index = 2
	await _rebuild()
	await _save("stage_3_dusk")
	get_tree().quit()


## **影の作り方2種を切り分けて撮る。** どちらが何を担当しているかを見る。
func _shadows_() -> void:
	_time_index = 3
	_lights_on = true
	_stage = 2                                # シェーダなしで比べる
	for mode in [0, 4, 1, 2, 7]:
		_shadow_mode = mode
		await _rebuild()
		await _save("shadow_%d" % mode)
	get_tree().quit()


## **height の効く単位が分からなかったので総当たりで確かめた**（第22節）。
func _sweep() -> void:
	_time_index = 3
	_lights_on = true
	for hs in [1.0, 16.0, 64.0, 128.0, 256.0, 512.0]:
		_height_scale = hs
		await _rebuild()
		await _save("sweep_%04d" % int(hs))
	get_tree().quit()


func _shoot() -> void:
	await _save("shot_%s_%d_%s" % [TIME_NAMES[_time_index], _stage,
		"light" if _lights_on else "flat"])
