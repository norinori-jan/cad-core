from __future__ import annotations

"""
core/sketch.py
──────────────────────────────────────────────────────────────────────
2D Sketch システム。

【仕様（固定）】
Primitive（3D）と Sketch（2D）は明確に別の経路として扱う：

    JSON
     ├── primitives   … 3D primitive (box/sphere/cylinder/cone/torus)
     ├── sketches     … 2D geometry (line/circle/arc/rectangle/polygon)
     └── operations   … boolean(cut等) / fillet / chamfer / extrude

    Sketch → geometry → profile → extrude → Solid
                                      ↓
                            selection → fillet/chamfer/boolean

このモジュールは「Sketch → profile」までを担当する。
profile を実際に立体化する extrude 操作は engine.py 側(_apply_operation)が行う。

【内部データモデル（今回拡張）】

    Sketch
      │ contains
      ▼
    Geometry
      │
      ├─ Basic Geometry      : line / circle / arc
      └─ Convenience Geometry: rectangle / polygon
      │
      ▼ normalize（Convenience → Basic Geometryのlineに分解）
    Closed Loops（line/arcの端点を突き合わせて閉ループをトレース。circleは単独で閉ループ）
      │
      ▼
    Profile（outer 1つ + inner(穴) 0個以上。bounding boxの内包関係で自動判定）
      │
      ▼ extrude
    Solid

【現時点でのスコープ（正直に明記する）】
- circle / rectangle / polygon … 単体で閉じた輪郭になるため、そのままextrude可能。
- line / arc … 複数を端点で連結して閉ループを作る(実装済み)。トレース前に各端点の接続数を検証し、
  未接続(開いている)・分岐(3本以上が同一点)を先に検出してSketchErrorとする。
- arcの角度は(a1-a0)を0〜360に正規化したCCW sweepとして解釈する(例: 350°→10°は20°の短い弧)。
  start_angle==end_angle(sweep=0)は未対応、full circleはtype="circle"を使うこと。
- 複数の閉ループがある場合、bounding boxベースの包含関係でouter(1つ)+inner(穴、outerに直接
  内包されるもの)の2階層構成のみ対応。3階層以上のネスト(穴の中の島)や、互いに内包しない複数の
  独立した輪郭はSketchError。
- 内包判定はbounding box基準の簡易判定であり、真の点in多角形判定ではない。凹形状などでは
  誤判定の可能性があるため、ローカルでの実行確認が必須。
- radius/width/height/polygon面積/line長がゼロまたは負(実質縮退)の場合はSketchError。
- line/arcの端点は、Wire組み立て前にvertex welding(tolerance内の点を完全一致座標へ統一)を行う。
  OCCTのBRepBuilderAPI_MakeWireがPython側判定より厳しい許容誤差を使うため必要な前処理。
  arcの端点(角度から計算され直接動かせない)をcanonicalとして優先する。
- Sketchのposition/rotation(配置のtransform)は今回実装しない。Phase2として明確に切り離す。
  現状は常に世界XY平面・原点・+Z方向extrudeのみ(plane != "XY"はSketchError)。
"""

import math
import cadquery as cq


class SketchError(Exception):
    """Sketch定義が不正、または2D形状の構築に失敗した場合の例外。"""


# ──────────────────────────────────────────────────────────────
# Basic Geometry: line / circle / arc の edge 構築
# ──────────────────────────────────────────────────────────────

def _build_line_edge(geo: dict) -> cq.Edge:
    """line: {"type":"line","start":[x,y],"end":[x,y]} → 1本のエッジ。単体では閉じていない。"""
    start = geo.get("start")
    end = geo.get("end")
    if not start or not end:
        raise SketchError("lineにはstart/endが必要です")
    if abs(start[0] - end[0]) < _ENDPOINT_TOL and abs(start[1] - end[1]) < _ENDPOINT_TOL:
        raise SketchError(f"lineのstart/endが同一点です(start={start}, end={end})")
    return cq.Edge.makeLine(cq.Vector(*start, 0), cq.Vector(*end, 0))


def _build_arc_edge(geo: dict) -> cq.Edge:
    """
    arc: {"type":"arc","center":[x,y],"radius":r,"start_angle":deg,"end_angle":deg}
    → 1本の円弧エッジ。単体では閉じていない。度数法、反時計回り(CCW)のsweepで解釈する。

    例: start_angle=350, end_angle=10 は「350°から反時計回りに20°進んで10°に到達する」
    短い円弧として扱う((a1-a0)を0〜360の範囲に正規化したsweepを使うため)。
    start_angle == end_angle(sweep=0)はfull circleと区別できないため未対応とし、
    full circleが欲しい場合はtype="circle"を使うこと。
    """
    cx, cy = geo.get("center", [0, 0])
    radius = geo.get("radius")
    a0 = geo.get("start_angle")
    a1 = geo.get("end_angle")
    if radius is None or a0 is None or a1 is None:
        raise SketchError("arcにはradius/start_angle/end_angleが必要です")
    if radius <= 0:
        raise SketchError(f"arcのradiusは正の値である必要があります(指定値: {radius})")

    sweep = (a1 - a0) % 360
    if sweep == 0:
        raise SketchError(
            "arcのstart_angleとend_angleが同一(sweep=0または360)です。"
            "full circleはtype='circle'を使ってください"
        )
    mid_angle = a0 + sweep / 2

    def _pt(angle_deg: float) -> tuple[float, float]:
        return (cx + radius * math.cos(math.radians(angle_deg)), cy + radius * math.sin(math.radians(angle_deg)))

    start = _pt(a0)
    mid = _pt(mid_angle)
    end = _pt(a1)

    return cq.Edge.makeThreePointArc(
        cq.Vector(*start, 0), cq.Vector(*mid, 0), cq.Vector(*end, 0)
    )


def _build_circle_edge(geo: dict) -> cq.Edge:
    """circle: {"type":"circle","center":[x,y],"radius":r} → 単独で閉じた円エッジ。"""
    cx, cy = geo.get("center", [0, 0])
    radius = geo.get("radius")
    if radius is None:
        raise SketchError("circleにはradiusが必要です")
    if radius <= 0:
        raise SketchError(f"circleのradiusは正の値である必要があります(指定値: {radius})")
    return cq.Edge.makeCircle(radius, cq.Vector(cx, cy, 0))


_BASIC_EDGE_BUILDERS = {
    "line": _build_line_edge,
    "arc": _build_arc_edge,
    "circle": _build_circle_edge,
}


# ──────────────────────────────────────────────────────────────
# normalize: Convenience Geometry(rectangle/polygon) → Basic Geometry(line)
# ──────────────────────────────────────────────────────────────

def _normalize_rectangle(geo: dict) -> list[dict]:
    """rectangle: {"type":"rectangle","center":[x,y],"width":w,"height":h} → 4本のline"""
    cx, cy = geo.get("center", [0, 0])
    width = geo.get("width")
    height = geo.get("height")
    if width is None or height is None:
        raise SketchError("rectangleにはwidth/heightが必要です")
    if width <= 0 or height <= 0:
        raise SketchError(f"rectangleのwidth/heightは正の値である必要があります(width={width}, height={height})")
    hw, hh = width / 2, height / 2
    corners = [
        (cx - hw, cy - hh),
        (cx + hw, cy - hh),
        (cx + hw, cy + hh),
        (cx - hw, cy + hh),
    ]
    return [
        {"type": "line", "start": list(corners[i]), "end": list(corners[(i + 1) % 4])}
        for i in range(4)
    ]


_AREA_TOL = 1e-9


def _polygon_signed_area(points: list) -> float:
    n = len(points)
    area = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _normalize_polygon(geo: dict) -> list[dict]:
    """polygon: {"type":"polygon","points":[[x,y],...]}（3点以上） → N本のline"""
    points = geo.get("points")
    if not points or len(points) < 3:
        raise SketchError("polygonには3点以上のpointsが必要です")
    if abs(_polygon_signed_area(points)) < _AREA_TOL:
        raise SketchError("polygonの面積が実質ゼロです(点が一直線上、または縮退しています)")
    n = len(points)
    return [
        {"type": "line", "start": list(points[i]), "end": list(points[(i + 1) % n])}
        for i in range(n)
    ]


_NORMALIZERS = {
    "rectangle": _normalize_rectangle,
    "polygon": _normalize_polygon,
}


def _normalize_geometry(geometry_list: list[dict]) -> list[dict]:
    """Convenience Geometryをline(Basic Geometry)に分解する。line/arc/circleはそのまま通す。"""
    normalized: list[dict] = []
    for geo in geometry_list:
        gtype = geo.get("type")
        if gtype in _NORMALIZERS:
            normalized.extend(_NORMALIZERS[gtype](geo))
        elif gtype in _BASIC_EDGE_BUILDERS:
            normalized.append(geo)
        else:
            raise SketchError(f"未対応のgeometry種別: {gtype!r}")
    return normalized


# ──────────────────────────────────────────────────────────────
# Closed Loops: line/arcの端点を突き合わせて閉ループをトレースする
# ──────────────────────────────────────────────────────────────

_ENDPOINT_TOL = 1e-6


def _endpoint(edge: cq.Edge, which: str) -> tuple[float, float]:
    v = edge.startPoint() if which == "start" else edge.endPoint()
    return (v.x, v.y)


def _close_enough(a: tuple[float, float], b: tuple[float, float], tol: float = _ENDPOINT_TOL) -> bool:
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def _validate_endpoint_degree(edges: list[cq.Edge]) -> None:
    """
    閉ループとして正しいなら、どの端点も「他の辺の端点」とちょうど1つだけ一致するはず
    (自分の辺の反対側の端点を除く)。0個なら未接続(開いている)、2個以上なら分岐(Y字路)。
    どちらもトレース時に「最初に見つかった辺を勝手に選ぶ」誤動作の原因になるため、
    トレース前に検出してエラーにする。
    """
    endpoints: list[tuple[float, float]] = []
    for e in edges:
        endpoints.append(_endpoint(e, "start"))
        endpoints.append(_endpoint(e, "end"))

    n = len(endpoints)
    for i in range(n):
        edge_idx = i // 2
        partner_idx = i + 1 if i % 2 == 0 else i - 1  # 自分の辺のもう一方の端点
        match_count = 0
        for j in range(n):
            if j == i or j == partner_idx:
                continue
            if _close_enough(endpoints[i], endpoints[j]):
                match_count += 1
        if match_count == 0:
            raise SketchError(
                f"line/arcの端点が閉じていません(どこにも接続しない端点: "
                f"({endpoints[i][0]:.4f}, {endpoints[i][1]:.4f})、辺index={edge_idx})"
            )
        if match_count > 1:
            raise SketchError(
                f"line/arcの端点で分岐(3本以上の辺が同一点で接続)が検出されました: "
                f"({endpoints[i][0]:.4f}, {endpoints[i][1]:.4f})。"
                "分岐のない単純な閉ループのみ対応しています。"
            )


def _geo_endpoints_raw(geo: dict) -> tuple[tuple[float, float], tuple[float, float]]:
    """line/arcの端点座標(x, y)を、OCCT Edgeを作らずに計算する(welding前処理用)。"""
    if geo["type"] == "line":
        start = geo.get("start")
        end = geo.get("end")
        return (tuple(start), tuple(end))
    if geo["type"] == "arc":
        cx, cy = geo.get("center", [0, 0])
        radius = geo.get("radius")
        a0 = geo.get("start_angle")
        a1 = geo.get("end_angle")
        start = (cx + radius * math.cos(math.radians(a0)), cy + radius * math.sin(math.radians(a0)))
        end = (cx + radius * math.cos(math.radians(a1)), cy + radius * math.sin(math.radians(a1)))
        return (start, end)
    raise SketchError(f"端点を持たないgeometry種別です: {geo['type']!r}")


def _weld_open_geometry_endpoints(open_geo: list[dict]) -> list[dict]:
    """
    line/arcの端点座標を突き合わせて、tolerance内の点を完全に同一座標へ統一する(vertex welding)。

    なぜ必要か: OCCTのBRepBuilderAPI_MakeWireは、Python側のtolerance判定(_ENDPOINT_TOL)より
    厳しい許容誤差で端点の一致を判定するため、"ほぼ同じ座標"(例: 手入力で丸めた値と
    三角関数で計算した値の1e-7オーダーの誤差)でもDisconnectedWireとして拒否されることがある。
    そのため、Python側でtolerance内と判定した端点は、Wireを組む前に完全一致する座標へ
    スナップしておく。

    arcの端点(start_angle/end_angleの三角関数で決まり、直接動かせない)がクラスタに含まれる
    場合はそれをcanonicalとして優先し、lineの端点だけをそこへスナップする。
    """
    n = len(open_geo)
    raw_points: list[list[tuple[float, float]]] = [list(_geo_endpoints_raw(g)) for g in open_geo]

    keys = [(i, k) for i in range(n) for k in (0, 1)]
    canonical: dict[tuple[int, int], tuple[float, float]] = {}
    visited: set[tuple[int, int]] = set()

    for key in keys:
        if key in visited:
            continue
        i, k = key
        cluster = [key]
        visited.add(key)
        pt = raw_points[i][k]
        for other in keys:
            if other in visited:
                continue
            oi, ok = other
            if _close_enough(pt, raw_points[oi][ok]):
                cluster.append(other)
                visited.add(other)

        canon_pt = pt
        for (ci, ck) in cluster:
            if open_geo[ci]["type"] == "arc":
                canon_pt = raw_points[ci][ck]
                break
        for ckey in cluster:
            canonical[ckey] = canon_pt

    welded: list[dict] = []
    for i, geo in enumerate(open_geo):
        if geo["type"] == "line":
            welded.append({
                "type": "line",
                "start": list(canonical[(i, 0)]),
                "end": list(canonical[(i, 1)]),
            })
        else:
            welded.append(geo)  # arcはそのまま(角度定義は変更しない)

    return welded


def _trace_open_loops(open_geo: list[dict]) -> list[cq.Wire]:
    """
    line/arcのgeometryリストから、端点を突き合わせて閉じたWireを1つ以上トレースする。
    複数の独立したループ(例: 外形1つ+穴用の輪郭1つをline/arcで組んだ場合)にも対応する。
    トレース前にvertex weldingで端点座標を統一し、さらに接続関係を検証して
    未接続や分岐があれば先に弾く。
    """
    welded_geo = _weld_open_geometry_endpoints(open_geo)
    edges = [_BASIC_EDGE_BUILDERS[g["type"]](g) for g in welded_geo]
    _validate_endpoint_degree(edges)

    used = [False] * len(edges)
    loops: list[cq.Wire] = []

    for start_idx in range(len(edges)):
        if used[start_idx]:
            continue
        chain = [edges[start_idx]]
        used[start_idx] = True
        loop_start = _endpoint(chain[0], "start")
        current = _endpoint(chain[0], "end")

        while not _close_enough(current, loop_start):
            next_idx = None
            next_point = None
            for i, e in enumerate(edges):
                if used[i]:
                    continue
                if _close_enough(_endpoint(e, "start"), current):
                    next_idx, next_point = i, _endpoint(e, "end")
                    break
                if _close_enough(_endpoint(e, "end"), current):
                    next_idx, next_point = i, _endpoint(e, "start")
                    break
            if next_idx is None:
                raise SketchError(
                    "line/arcの端点が閉じたループを形成していません"
                    f"(現在位置 ({current[0]:.4f}, {current[1]:.4f}) に接続する辺が見つかりません)"
                )
            chain.append(edges[next_idx])
            used[next_idx] = True
            current = next_point

        loops.append(cq.Wire.assembleEdges(chain))

    return loops


def _closed_loops_from_geometry(geometry_list: list[dict]) -> list[cq.Wire]:
    """正規化済みgeometryから、circle(単独閉ループ)とline/arc(トレースして閉ループ)を統合する。"""
    normalized = _normalize_geometry(geometry_list)
    circle_geo = [g for g in normalized if g["type"] == "circle"]
    open_geo = [g for g in normalized if g["type"] in ("line", "arc")]

    loops = [cq.Wire.assembleEdges([_build_circle_edge(g)]) for g in circle_geo]
    if open_geo:
        loops.extend(_trace_open_loops(open_geo))

    if not loops:
        raise SketchError("sketchのgeometryから閉じた輪郭を1つも構成できませんでした")
    return loops


# ──────────────────────────────────────────────────────────────
# Profile: outer 1つ + inner(穴) 0個以上
# ──────────────────────────────────────────────────────────────

def _bbox_contains(outer_bb, inner_bb, margin: float = 1e-6) -> bool:
    return (
        inner_bb.xmin >= outer_bb.xmin - margin
        and inner_bb.xmax <= outer_bb.xmax + margin
        and inner_bb.ymin >= outer_bb.ymin - margin
        and inner_bb.ymax <= outer_bb.ymax + margin
    )


def _build_profile_face(loops: list[cq.Wire]) -> cq.Face:
    """
    複数の閉ループから、包含関係のグラフを作りouter(誰にも内包されない1つ)とinner(穴。
    outerに直接内包される)を判定してProfile(穴あき面)を構築する。

    2階層(outer + inner)までしか対応しない。穴の中にさらに島がある3階層以上の構成や、
    どちらにも内包されない独立した複数輪郭はSketchErrorとする。

    NOTE: 内包判定はbounding box基準の簡易判定であり、真の点in多角形判定ではない。
    凹形状などでは誤判定の可能性があるため、ローカルでの実行確認が必須。
    """
    if len(loops) == 1:
        return cq.Face.makeFromWires(loops[0])

    n = len(loops)
    bboxes = [w.BoundingBox() for w in loops]

    # contains[i][j] == True: loop i が loop j をbbox基準で内包している
    contains = [[False] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j and _bbox_contains(bboxes[i], bboxes[j]):
                contains[i][j] = True

    contained_by_count = [sum(contains[i][j] for i in range(n)) for j in range(n)]
    if max(contained_by_count) > 1:
        raise SketchError(
            "3階層以上のネスト(穴の中に島がある構成)は未対応です。"
            "outer + inner(穴)の2階層構成のみサポートしています。"
        )

    roots = [j for j in range(n) if contained_by_count[j] == 0]
    if len(roots) != 1:
        raise SketchError(
            "outer(どのループにも内包されない輪郭)が1つに定まりません。"
            "複数のloopがある場合はouterがinner(穴)を内包する構成にしてください。"
        )
    outer_idx = roots[0]
    inner_indices = [j for j in range(n) if contains[outer_idx][j]]
    if len(inner_indices) != n - 1:
        raise SketchError(
            "outerに内包されないループがあります。互いに重ならない複数の独立した輪郭は未対応です。"
        )

    outer = loops[outer_idx]
    inner_wires = [loops[j] for j in inner_indices]
    return cq.Face.makeFromWires(outer, inner_wires)


def build_profile(sketch_def: dict) -> cq.Face:
    """
    Sketch定義（geometryのリスト）から、1つのProfile(押し出し可能な面。穴があってもよい)を構築する。

    plane（"XY"等）は現時点ではXYのみを検証済み。それ以外は将来対応。
    """
    plane = sketch_def.get("plane", "XY")
    if plane != "XY":
        raise SketchError(f"現時点ではplane='XY'のみ対応しています(指定値: {plane!r})")

    geometry_list = sketch_def.get("geometry", [])
    if not geometry_list:
        raise SketchError("sketchのgeometryが空です")

    loops = _closed_loops_from_geometry(geometry_list)
    return _build_profile_face(loops)


def extrude_sketch(face: cq.Face, distance: float) -> cq.Workplane:
    """build_profile()の結果(cq.Face)を実際に立体化する。"""
    try:
        solid = cq.Solid.extrudeLinear(face, cq.Vector(0, 0, distance))
        return cq.Workplane("XY").newObject([solid])
    except Exception as e:
        raise SketchError(f"スケッチの押し出しに失敗しました: {e}") from e
