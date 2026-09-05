extends Node2D
## 納品済みの素材に 2Dライトとノーマルマップを乗せ、見え方を確かめる。
##
## **ゲーム本体ではない。** 素材リポジトリの assets/ を直接読む。
## 作り直しは一切しない。
##
##   1..4  時間帯（朝・昼・夕・夜）
##   L     ライトの入切
##   N     ノーマルマップの入切
##   S     スクリーンショット（user:// へ保存）
##
## 時間帯は **CanvasModulate の色調**で作る。パレット置換（時間帯ごとに
## 色を差し替える設計）は本来シェーダで行うが、ここでは見え方の確認が
## 目的なので色調の乗算で近似している。**この違いは報告に明記する。**

const ASSETS := "res://assets"
const TILE := 32
const W := 30
const H := 14

var _time_index := 3          # 既定は夜。**本作の核となる絵**
var _lights_on := true
var _normals_on := true
var _height_scale := 1.0

var _ground := Node2D.new()
var _objects := Node2D.new()
var _light_root := Node2D.new()
var _modulate := CanvasModulate.new()
var _label := Label.new()

## 時間帯ごとの全体色調。**夜は藍へ大きく沈める。**
const TINTS := {
	0: Color(0.72, 0.76, 0.86),   # 朝  湿って青い
	1: Color(1.00, 1.00, 1.00),   # 昼  基準
	2: Color(0.86, 0.74, 0.66),   # 夕  光が弱り土へ寄る
	3: Color(0.20, 0.24, 0.40),   # 夜  藍へ沈む
}
const TIME_NAMES := ["朝", "昼", "夕", "夜"]


func _ready() -> void:
	add_child(_ground)
	add_child(_objects)
	add_child(_light_root)
	add_child(_modulate)
	_build_ground()
	_build_objects()
	_build_lights()
	_build_hud()
	_apply_time()
	# **自動撮影。** --auto を付けて起動すると、必要な絵をすべて撮って終了する。
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--height="):
			_height_scale = float(a.split("=")[1])
		if a == "--sweep":
			_label.visible = false
			call_deferred("_sweep")
		if a == "--auto":
			_label.visible = false
			call_deferred("_auto_capture")


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


func _put(tex: Texture2D, x: int, y: int, parent: Node2D, normal: bool = true) -> void:
	if tex == null:
		return
	var s := Sprite2D.new()
	s.texture = tex
	s.centered = false
	s.position = Vector2(x, y)
	if normal:
		var n_path: String = tex.resource_path.get_basename() + "_n.png"
		if ResourceLoader.exists(n_path):
			var ct := CanvasTexture.new()
			ct.diffuse_texture = tex
			ct.normal_texture = load(n_path)
			s.texture = ct
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
		# **足元を基準に置く。** 立ち物は側面で描かれているので、
		# 画像の下端が接地点になる（第19節）。
		_put(tex, entry[1] * TILE, entry[2] * TILE - tex.get_height(), _objects)


## --- 光 -------------------------------------------------------------------
## **暗さと受光面は実行時に作る**（第5節）。素材には焼き込まない。
## height は **ノーマルマップの効きを決める**。既定の 0.0 は「光源が面と
## 同じ高さにある」意味になり、平らな面（法線は真上）への入射角が 90 度に
## なって**何も照らされない**。実際、0 のまま撮った夜の絵は、ノーマルマップを
## 切った絵より暗かった。
##
## **単位は画素である。** 0〜1 の正規化値ではない（総当たりで確かめた。
## 1 と 16 では暗いまま、64〜128 で正しい光溜まりになり、256 を超えると
## 逆に法線が効かなくなって平らな絵に戻る）。**灯体の実際の高さを画素で書く。**
func _add_light(pos: Vector2, colour: Color, energy: float, scale: float,
		height: float) -> void:
	var l := PointLight2D.new()
	l.texture = _radial_texture()
	l.position = pos
	l.color = colour
	l.energy = energy
	l.texture_scale = scale
	l.shadow_enabled = false
	l.height = height * _height_scale
	l.blend_mode = Light2D.BLEND_MODE_ADD
	l.set_meta("base_energy", energy)
	_light_root.add_child(l)


var _radial_cache: Texture2D


func _radial_texture() -> Texture2D:
	if _radial_cache:
		return _radial_cache
	var size := 256
	var img := Image.create(size, size, false, Image.FORMAT_RGBA8)
	var c := size * 0.5
	for y in range(size):
		for x in range(size):
			var d: float = Vector2(x - c, y - c).length() / c
			var a: float = clampf(1.0 - d, 0.0, 1.0)
			a = a * a                      # 二乗で自然な減衰
			img.set_pixel(x, y, Color(1, 1, 1, a))
	_radial_cache = ImageTexture.create_from_image(img)
	return _radial_cache


func _build_lights() -> void:
	# 自販機の発光面。**白緑。本作で最も彩度が許される色**
	#   発光面は地面から 24px ほど。**低いので路面を斜めに舐める**。
	_add_light(Vector2(7 * TILE + 16, 8 * TILE - 40), Color(0.30, 0.78, 0.68), 1.5, 1.1, 24.0)
	# 街灯。水銀灯はナトリウム橙、LED は青白。**灯体は 3m 相当＝48px 上にある**。
	_add_light(Vector2(11 * TILE + 16, 8 * TILE - 96), Color(0.78, 0.50, 0.18), 1.7, 1.6, 48.0)
	_add_light(Vector2(20 * TILE + 16, 8 * TILE - 96), Color(0.53, 0.69, 0.71), 1.5, 1.5, 48.0)
	# 月光。広く弱く、蒼白。**ほぼ真上から**なので高くして凹凸をつぶさない。
	_add_light(Vector2(W * TILE * 0.5, H * TILE * 0.35), Color(0.34, 0.40, 0.58), 0.55, 5.0, 96.0)


## --- 表示 -----------------------------------------------------------------
func _build_hud() -> void:
	_label.position = Vector2(4, 2)
	_label.add_theme_font_size_override("font_size", 8)
	_label.add_theme_color_override("font_color", Color(0.9, 0.9, 0.95))
	_label.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.8))
	_label.add_theme_constant_override("shadow_offset_y", 1)
	var layer := CanvasLayer.new()
	layer.add_child(_label)
	add_child(layer)


## 灯りの入り方は時間帯で変わる。**昼に街灯は点かない。**
## 最初は時間帯によらず全灯していたので、真昼の歩道に自販機の光溜まりが
## できていた。色調だけでなく**灯りの強さも時間帯の一部**である。
const LIGHT_GAIN := {0: 0.35, 1: 0.0, 2: 0.70, 3: 1.0}   # 人工光
const MOON_GAIN := {0: 0.25, 1: 0.0, 2: 0.45, 3: 1.0}    # 月光


func _apply_time() -> void:
	# **色調は光の入切と独立**。消灯した夜は「真っ暗な夜」であって昼ではない。
	_modulate.color = TINTS[_time_index]
	_light_root.visible = _lights_on
	var count := _light_root.get_child_count()
	for i in range(count):
		var l := _light_root.get_child(i) as PointLight2D
		var gain: float = MOON_GAIN[_time_index] if i == count - 1 else LIGHT_GAIN[_time_index]
		l.energy = float(l.get_meta("base_energy")) * gain
	_label.text = "%s   ライト:%s   ノーマル:%s   [1-4] 時間帯  [L] ライト  [N] ノーマル  [S] 保存" % [
		TIME_NAMES[_time_index],
		"入" if _lights_on else "切",
		"入" if _normals_on else "切"]
	_set_normals(_normals_on)


func _set_normals(on: bool) -> void:
	for parent in [_ground, _objects]:
		for child in parent.get_children():
			var s := child as Sprite2D
			if s == null:
				continue
			var ct := s.texture as CanvasTexture
			if ct:
				ct.normal_texture = ct.normal_texture if on else null


func _unhandled_input(event: InputEvent) -> void:
	if not (event is InputEventKey and event.pressed and not event.echo):
		return
	match event.keycode:
		KEY_1, KEY_2, KEY_3, KEY_4:
			_time_index = event.keycode - KEY_1
			_apply_time()
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
	for parent in [_ground, _objects]:
		for child in parent.get_children():
			child.queue_free()
	await get_tree().process_frame
	_build_ground()
	_build_objects()
	_apply_time()


## 比較に要る絵を順に撮る。**同じ構図で、条件だけを変える。**
func _auto_capture() -> void:
	var shots := [
		# **昼は素材そのものが画面である。** 街灯も自販機も点かないので、
		# 「昼のライト入」は「昼のライト切」と一致する。撮っても意味がない。
		[1, false, true,  "01_daylight_flat"],
		[0, true,  true,  "03_morning"],
		[2, true,  true,  "04_dusk"],
		[3, true,  true,  "05_night"],             # **本作の核**
		[3, true,  false, "06_night_no_normal"],   # ノーマルマップの効きを見る
		[3, false, true,  "07_night_no_light"],
	]
	for shot in shots:
		_time_index = shot[0]
		_lights_on = shot[1]
		if _normals_on != shot[2]:
			_normals_on = shot[2]
			await _rebuild()
		else:
			_apply_time()
		await RenderingServer.frame_post_draw
		await get_tree().process_frame
		await RenderingServer.frame_post_draw
		var img := get_viewport().get_texture().get_image()
		var path := "user://%s.png" % shot[3]
		img.save_png(path)
		print("保存: ", ProjectSettings.globalize_path(path))
	get_tree().quit()


## **height の効く単位が分からない。** 総当たりで確かめる。
func _sweep() -> void:
	_time_index = 3
	_lights_on = true
	_normals_on = true
	for hs in [1.0, 16.0, 64.0, 128.0, 256.0, 512.0]:
		_height_scale = hs
		for child in _light_root.get_children():
			child.queue_free()
		await get_tree().process_frame
		_build_lights()
		_apply_time()
		await RenderingServer.frame_post_draw
		await get_tree().process_frame
		await RenderingServer.frame_post_draw
		var img := get_viewport().get_texture().get_image()
		img.save_png("user://sweep_%04d.png" % int(hs))
		print("保存: height x", hs)
	get_tree().quit()


func _shoot() -> void:
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	var name := "user://shot_%s_%s_%s.png" % [
		TIME_NAMES[_time_index], "light" if _lights_on else "flat",
		"n" if _normals_on else "nn"]
	img.save_png(name)
	print("保存: ", ProjectSettings.globalize_path(name))
