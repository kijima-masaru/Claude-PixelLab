"""手続き的に素材を作るための原始関数。**API を使わない。**

自作画像から素材を切り出す経路（tools/tile_from_texture.py）には、
どうしても消せない弱点が2つある。

  - 素材が画面に映っているものに限られる。1枚の画面で 5/27 が上限だった
  - **切り出した窓は端が合わない。** 継ぎ目はランダム配置で誤魔化すしかない

ここは逆である。**すべての関数がトーラス（周期境界）上で生成する。**
したがって**継ぎ目は原理的に生じない。** 256x256 の面を作れば
8x8=64 枚のタイルが、互いに完全に繋がった状態で得られる。

原始関数は4つ。素材はこの組み合わせで作る。

    fbm            大きく低コントラストな斑。土・草・水・コンクリート
    strokes        短い線の散布。草・落ち葉・木目
    voronoi        不規則な区画。石畳・砂利・礫・崩れた礎石
    grid / waves   規則的な格子と正弦波。畳・板張り・トタン・法枠

**32px において素材らしさを作るのは、細かい模様ではない**（第11節）。
どの関数も、出力を最後にコントラスト圧縮してから使うこと。
等倍で焼くと迷彩柄になる。
"""

from __future__ import annotations

import colorsys
import math
import random


# ---------------------------------------------------------------------------
# 1. 値ノイズと fBm
# ---------------------------------------------------------------------------

def value_noise(size: int, cells: int, seed: int) -> list:
    """トーラス上の値ノイズ。cells x cells の格子を余弦補間する。

    格子の添字を cells で剰余するだけで周期境界になる。**これが継ぎ目が
    生じない理由である。** 補間を線形ではなく余弦にするのは、
    線形だと格子の交点に折れ目が見えるため。
    """
    rng = random.Random(seed)
    lattice = [[rng.random() for _ in range(cells)] for _ in range(cells)]
    step = size / cells
    field = []
    for y in range(size):
        fy = y / step
        y0 = int(fy) % cells
        y1 = (y0 + 1) % cells
        ty = (1 - math.cos((fy - int(fy)) * math.pi)) / 2
        row = []
        for x in range(size):
            fx = x / step
            x0 = int(fx) % cells
            x1 = (x0 + 1) % cells
            tx = (1 - math.cos((fx - int(fx)) * math.pi)) / 2
            top = lattice[y0][x0] * (1 - tx) + lattice[y0][x1] * tx
            bottom = lattice[y1][x0] * (1 - tx) + lattice[y1][x1] * tx
            row.append(top * (1 - ty) + bottom * ty)
        field.append(row)
    return field


def fbm(size: int, octaves: int, seed: int, base_cells: int = 16,
        gain: float = 0.5) -> list:
    """値ノイズを重ねる。**「大きく低コントラストな斑」を作るのが狙い。**

    base_cells は最も粗いオクターブの格子数。**斑の大きさを決める
    最重要のパラメータである。** 実測（256px の面）:

        base_cells= 4  斑が大きすぎて、雲のように見える
        base_cells= 8  ざらつき 2.5 前後。目標帯を下回る
        base_cells=16  ざらつき 3.7〜4.7。**目標帯（3.5〜6.0）に入る**

    octaves を増やすと細かい粒が乗る。gain は各段の減衰。
    """
    field = [[0.0] * size for _ in range(size)]
    amplitude, total, cells = 1.0, 0.0, base_cells
    for index in range(octaves):
        layer = value_noise(size, cells, seed + index * 101)
        for y in range(size):
            for x in range(size):
                field[y][x] += layer[y][x] * amplitude
        total += amplitude
        amplitude *= gain
        cells *= 2
    return [[v / total for v in row] for row in field]


# ---------------------------------------------------------------------------
# 2. ボロノイ分割
# ---------------------------------------------------------------------------

def voronoi(size: int, points: int, seed: int, jitter: float = 1.0) -> tuple:
    """トーラス上のボロノイ図。(区画の番号, 境界までの距離) を返す。

    石畳・砂利・礫・崩れた礎石はすべて「不規則な区画の集まり」であり、
    ボロノイがそのまま形になる。**ノイズでは作れない唯一の形である。**

    種を格子状に置いて jitter で乱すと、区画の大きさが揃う（石畳向き）。
    jitter を上げると大きさがばらつく（礫・崩れた石向き）。

    距離は最近傍と次近傍の差（F2 - F1）で測る。**この値が小さい所が
    区画の境界であり、そこに目地を描く。** 単純な F1 だと区画の
    中心からの距離になってしまい、目地が引けない。
    """
    rng = random.Random(seed)
    side = max(1, int(round(math.sqrt(points))))
    step = size / side
    seeds = []
    for gy in range(side):
        for gx in range(side):
            seeds.append(((gx + 0.5 + rng.uniform(-0.5, 0.5) * jitter) * step,
                          (gy + 0.5 + rng.uniform(-0.5, 0.5) * jitter) * step))
    cell = [[0] * size for _ in range(size)]
    edge = [[0.0] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            best = second = None
            best_i = 0
            for i, (sx, sy) in enumerate(seeds):
                dx = abs(x - sx)
                dy = abs(y - sy)
                dx = min(dx, size - dx)          # トーラス上の距離
                dy = min(dy, size - dy)
                d = dx * dx + dy * dy
                if best is None or d < best:
                    second, best, best_i = best, d, i
                elif second is None or d < second:
                    second = d
            cell[y][x] = best_i
            edge[y][x] = math.sqrt(second) - math.sqrt(best) if second else 99.0
    return cell, edge


# ---------------------------------------------------------------------------
# 3. 規則格子と正弦波
# ---------------------------------------------------------------------------

def grid(size: int, pitch_x: int, pitch_y: int, offset_rows: float = 0.0,
         line: int = 1) -> list:
    """規則的な格子。1 が目地・継ぎ目、0 が面。

    畳・板張り・タイル・法枠はすべてこれである。**規則的な素材は
    生成 API より手続き的生成のほうが確実に正確である**（プログラムは
    格子を正確に描ける。生成モデルは歪ませる）。

    offset_rows は行ごとの横ずらし量（pitch_x に対する割合）。
    0.5 にすると煉瓦積み（馬目地）になる。板張りの継ぎ目にも使う。

    **pitch は size を割り切る値にすること。** そうでないと周期境界で
    格子がずれ、タイルの継ぎ目に段差が出る。
    """
    out = [[0] * size for _ in range(size)]
    for y in range(size):
        row_index = y // pitch_y
        shift = int(row_index * offset_rows * pitch_x) % pitch_x
        horizontal = (y % pitch_y) < line
        for x in range(size):
            vertical = ((x + shift) % pitch_x) < line
            out[y][x] = 1 if (horizontal or vertical) else 0
    return out


def waves(size: int, period: int, axis: str = "x", phase: float = 0.0) -> list:
    """正弦波。0.0〜1.0 の断面を返す。トタン屋根・波板・畝。

    **period は size を割り切る値にすること**（周期境界のため）。
    """
    out = [[0.0] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            t = (x if axis == "x" else y) / period * 2 * math.pi + phase
            out[y][x] = (math.sin(t) + 1) / 2
    return out


# ---------------------------------------------------------------------------
# 4. 短い線の散布
# ---------------------------------------------------------------------------

def strokes(size: int, count: int, seed: int, length: int = 3,
            angle: float | None = None, mask: list | None = None) -> list:
    """短い線を散らす。1 が線の乗った画素。

    **草は面ではなく、無数の線の集合である。** 落ち葉・杉の針葉・
    木目も同じ。angle を None にすると向きがばらつき（草）、
    値を与えると向きが揃う（木目・針葉）。

    mask を渡すと、そこが真の位置にだけ生やす。
    「窪みには草が生えない」といった条件を noise で与えるために使う。
    """
    rng = random.Random(seed)
    out = [[0] * size for _ in range(size)]
    for _ in range(count):
        x0 = rng.randrange(size)
        y0 = rng.randrange(size)
        if mask is not None and not mask[y0][x0]:
            continue
        theta = rng.uniform(0, 2 * math.pi) if angle is None else angle
        dx, dy = math.cos(theta), math.sin(theta)
        for step in range(rng.randint(1, length)):
            out[int(y0 + dy * step) % size][int(x0 + dx * step) % size] = 1
    return out


# ---------------------------------------------------------------------------
# ランプ（パレットの一部を取り出す）
# ---------------------------------------------------------------------------

#: 色相帯の定義。パレットの系統に対応する。
HUE_BANDS = {
    "earth": (5, 45),
    "green": (100, 175),
    "indigo": (195, 250),
    "violet": (250, 290),
}


def ramp(palette: list, band: str, min_s: float = 0.10,
         lo: float = 0.0, hi: float = 1.0) -> list:
    """パレットから、ある系統の色を明度順に取り出す。

    lo / hi で使う範囲を切る。**「褪せた」を作るのは主にここである。**
    たとえば green の下半分だけを使えば、鮮やかな緑が物理的に出せない。
    """
    low, high = HUE_BANDS[band]
    picked = []
    for colour in palette:
        h, l, s = colorsys.rgb_to_hls(*[v / 255 for v in colour])
        if low <= h * 360 <= high and s >= min_s:
            picked.append((l, colour))
    ordered = [c for _, c in sorted(picked)]
    if not ordered:
        return ordered
    start = int(lo * (len(ordered) - 1))
    end = int(hi * (len(ordered) - 1))
    return ordered[start:end + 1] or [ordered[start]]


def neutrals(palette: list, max_s: float = 0.13) -> list:
    """ほぼ中性の灰色だけを明度順に返す。コンクリート・アスファルト用。"""
    picked = []
    for colour in palette:
        _, l, s = colorsys.rgb_to_hls(*[v / 255 for v in colour])
        if s <= max_s:
            picked.append((l, colour))
    return [c for _, c in sorted(picked)]


# ---------------------------------------------------------------------------
# 反復の目立ちやすさ
# ---------------------------------------------------------------------------

def _luma(image):
    px = image.convert("RGB").load()
    w, h = image.size
    return [[0.299 * px[x, y][0] + 0.587 * px[x, y][1] + 0.114 * px[x, y][2]
             for x in range(w)] for y in range(h)]


def _corr_at(grid, dx, dy):
    """ずらし量 (dx, dy) での正規化自己相関。トーラスではなく重なりで測る。"""
    h, w = len(grid), len(grid[0])
    mean = sum(sum(r) for r in grid) / (w * h)
    num = da = db = 0.0
    for y in range(h - dy):
        for x in range(w - dx):
            a = grid[y][x] - mean
            b = grid[y + dy][x + dx] - mean
            num += a * b
            da += a * a
            db += b * b
    return num / (da * db) ** 0.5 if da and db else 0.0


#: 「格子に乗らない」ずらし量。**1px でなければならない。**
#: 素材そのものの相関は 1px ずらした程度では変わらないため、差を取れば
#: 異方性が相殺される。大きくすると素材の相関まで変わってしまい、
#: 縞素材が再び不合格になる（5px で試して失敗した）。
OFF_LATTICE = 1


def grid_visibility(image, tile: int = 32, period: int = 8) -> float:
    """**32px のタイル格子が、どれだけ目立つか。** 0〜1。低いほどよい。

    従来の `periodicity()` は「1枚のタイルを自分自身で反復したときの
    目立ちやすさ」を測るものだった。**手続き的生成には当てはまらない。**
    256px のトーラス面から 8x8=64 枚を切り出すため、反復の周期は
    32px ではなく **8タイル**である。32px の切片を測っても、
    実際の見え方と対応しない。

    ここでは**敷き詰めた面**を入力に取り、タイル幅の整数倍だけずらした
    ときの自己相関を見る。**ただし周期そのもの（8タイル）は除く。**
    そこが一致するのは設計どおりであって、欠陥ではない。

    | 値 | 意味 |
    | --- | --- |
    | 0.9 以上 | 1枚のタイルが反復している。**壁紙** |
    | 0.5〜0.9 | 格子が読める |
    | **0.35 未満** | **格子が見えない**（目視と一致することを確認済み） |
    """
    grid = _luma(image)
    best = 0.0
    for k in range(1, period):
        for dx, dy in ((k * tile, 0), (0, k * tile)):
            if dx >= image.size[0] - tile - OFF_LATTICE or dy >= image.size[1] - tile - OFF_LATTICE:
                continue
            # ★ **格子に乗るずらしと、乗らないずらしの差を見る。**
            #
            # 縞模様の素材は、繊維の方向にずらしても同じに見える。それは
            # タイルの継ぎ目ではなく**素材そのものの異方性**である。
            # 実測（トタン屋根）: 32pxずらし 0.888 / 33pxずらし 0.859。
            # **差は 0.029 しかない。** 生の値を見ると縞素材が軒並み
            # 不合格になるが、タイル由来の成分はほぼゼロだった。
            #
            # 異方性は両方のずらしに等しく出るため、差を取れば相殺される。
            # **絶対値を取ってはならない。** 壁紙とは「ずらしても同じ」
            # ことであり、正の相関である。**負の相関はむしろ逆**であって、
            # タイルが同一でないことを示す。絶対値を取ると、位相が
            # 半周期ずれた縞（相関 -0.888）を「壁紙」と誤判定する。
            off = _corr_at(grid, dx + OFF_LATTICE if dx else 0,
                           dy + OFF_LATTICE if dy else 0)
            best = max(best, _corr_at(grid, dx, dy) - off)
    return max(0.0, best)


def grain_ratio(image, coarse: int = 8, fine: int = 1) -> float:
    """**斑が「大きい」か「細かい」か。** ざらつきとは別の軸。

    ざらつきが同じでも、斑が大きいほど「模様」として認識される。
    実測（承認済みの `tile_asphalt_curb` と、初期の手続き的生成）:

        路面  ざらつき 4.53  相関長 1.5px  **帯域比 0.31**  ← 静かな面に見える
        土    ざらつき 3.77  相関長 6.0px  **帯域比 1.39**  ← 迷彩に見える
        草    ざらつき 4.27  相関長 6.5px  **帯域比 1.38**  ← 同上

    **数値上はどちらも目標帯（3.5〜6.0）に入っているのに、絵は別物だった。**
    ざらつきだけでは足りない。

    8〜16px の帯（大きい斑）のエネルギーを、1px の帯（細かい粒）で割る。
    **1 を超えると大きい斑が主役になり、模様として読まれる。**

    | 値 | 意味 |
    | --- | --- |
    | **0.3 前後** | **細かい粒が主。静かな面に見える**（路面がこれ） |
    | 0.6〜1.0 | 大小が拮抗する |
    | 1.0 以上 | 大きい斑が主。**迷彩に見える** |

    fbm の `gain` で直接動かせる。`gain` が 1 未満だと粗いオクターブが
    支配し（帯域比が上がる）、1 以上だと細かいオクターブが支配する。
    **標準的な fBm の既定（gain=0.5）は、地面の素材には向かない。**
    """
    from PIL import ImageFilter
    grey = image.convert("L")
    w, h = grey.size

    def energy(a: int, b: int) -> float:
        pa = (grey if a == 0 else grey.filter(ImageFilter.BoxBlur(a))).load()
        pb = grey.filter(ImageFilter.BoxBlur(b)).load()
        return sum(abs(pa[x, y] - pb[x, y]) for y in range(h) for x in range(w)) / (w * h)

    return energy(coarse, coarse * 2) / max(energy(0, fine), 0.01)
