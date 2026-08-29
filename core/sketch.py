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

【実装方式】
CadQueryのWorkplaneのワイヤーを手動で合成するのではなく、2D合成専用に
用意されている cq.Sketch クラスを使う(mode='a'で複数形状を加算合成できる)。

【現時点でのスコープ（正直に明記する）】
- circle / rectangle / polygon … 単体で閉じた輪郭になるため、そのままextrude可能。実装・検証済み。
- line / arc … 単体では閉じた輪郭にならない(押し出すと面にならず失敗する)。
  ジオメトリ生成自体は実装・検証済みだが、複数のline/arcを組み合わせて
  1つの閉じた輪郭を作る合成機能はまだ実装していない（将来のタスク）。
  現状、sketchのgeometryにline/arc単体しか無い場合、extrude時にSketchErrorとする。
"""

import math
import cadquery as cq


class SketchError(Exception):
    """Sketch定義が不正、または2D形状の構築に失敗した場合の例外。"""


def _add_circle(sk: cq.Sketch, geo: dict) -> cq.Sketch:
    """circle: {"type":"circle","center":[x,y],"radius":r}"""
    cx, cy = geo.get("center", [0, 0])
    radius = geo.get("radius")
    if radius is None:
        raise SketchError("circleにはradiusが必要です")
    return sk.push([(cx, cy)]).circle(radius, mode="a")


def _add_rectangle(sk: cq.Sketch, geo: dict) -> cq.Sketch:
    """rectangle: {"type":"rectangle","center":[x,y],"width":w,"height":h}"""
    cx, cy = geo.get("center", [0, 0])
    width = geo.get("width")
    height = geo.get("height")
    if width is None or height is None:
        raise SketchError("rectangleにはwidth/heightが必要です")
    return sk.push([(cx, cy)]).rect(width, height, mode="a")


def _add_polygon(sk: cq.Sketch, geo: dict) -> cq.Sketch:
    """polygon: {"type":"polygon","points":[[x,y],...]}（3点以上）"""
    points = geo.get("points")
    if not points or len(points) < 3:
        raise SketchError("polygonには3点以上のpointsが必要です")
    pts = [tuple(p) for p in points]
    return sk.polygon(pts, mode="a")


# 閉じた輪郭を作れる（＝単体でextrude可能な）geometry種別
_CLOSED_BUILDERS = {
    "circle": _add_circle,
    "rectangle": _add_rectangle,
    "polygon": _add_polygon,
}


def _build_line_edge(geo: dict) -> cq.Edge:
    """line: {"type":"line","start":[x,y],"end":[x,y]} → 1本のエッジ。単体では閉じていない。"""
    start = geo.get("start")
    end = geo.get("end")
    if not start or not end:
        raise SketchError("lineにはstart/endが必要です")
    return cq.Edge.makeLine(cq.Vector(*start, 0), cq.Vector(*end, 0))


def _build_arc_edge(geo: dict) -> cq.Edge:
    """
    arc: {"type":"arc","center":[x,y],"radius":r,"start_angle":deg,"end_angle":deg}
    → 1本の円弧エッジ。単体では閉じていない。度数法、反時計回りを正とする。
    """
    cx, cy = geo.get("center", [0, 0])
    radius = geo.get("radius")
    a0 = geo.get("start_angle")
    a1 = geo.get("end_angle")
    if radius is None or a0 is None or a1 is None:
        raise SketchError("arcにはradius/start_angle/end_angleが必要です")

    start = (cx + radius * math.cos(math.radians(a0)), cy + radius * math.sin(math.radians(a0)))
    end = (cx + radius * math.cos(math.radians(a1)), cy + radius * math.sin(math.radians(a1)))
    mid_angle = (a0 + a1) / 2
    mid = (cx + radius * math.cos(math.radians(mid_angle)), cy + radius * math.sin(math.radians(mid_angle)))

    return cq.Edge.makeThreePointArc(
        cq.Vector(*start, 0), cq.Vector(*mid, 0), cq.Vector(*end, 0)
    )


_OPEN_BUILDERS = {
    "line": _build_line_edge,
    "arc": _build_arc_edge,
}


def build_profile(sketch_def: dict) -> cq.Workplane:
    """
    Sketch定義（geometryのリスト）から、1つの2Dプロファイル(押し出し可能な面)を構築する。
    複数のgeometryが指定された場合は、和集合(union, mode='a')として1つのプロファイルにまとめる。

    plane（"XY"等）は現時点ではXYのみを検証済み。それ以外は将来対応。

    戻り値は cq.Workplane（.placeSketch()経由でextrudeできる状態にはせず、
    呼び出し側のengine.pyが cq.Workplane("XY").placeSketch(sketch).extrude(d) する）。
    """
    plane = sketch_def.get("plane", "XY")
    if plane != "XY":
        raise SketchError(f"現時点ではplane='XY'のみ対応しています(指定値: {plane!r})")

    geometry_list = sketch_def.get("geometry", [])
    if not geometry_list:
        raise SketchError("sketchのgeometryが空です")

    sk = cq.Sketch()
    added_closed = False

    for geo in geometry_list:
        gtype = geo.get("type")

        if gtype in _CLOSED_BUILDERS:
            sk = _CLOSED_BUILDERS[gtype](sk, geo)
            added_closed = True
        elif gtype in _OPEN_BUILDERS:
            # line/arc単体は閉じた輪郭にならないため、profileの面としては採用しない
            # (ジオメトリ自体は生成できることだけ検証。将来、複合ワイヤ生成を実装したら拡張する)
            _OPEN_BUILDERS[gtype](geo)
        else:
            raise SketchError(f"未対応のgeometry種別: {gtype!r}")

    if not added_closed:
        raise SketchError(
            "このsketchには閉じた輪郭(circle/rectangle/polygon)が含まれていません。"
            "line/arc単体からの複合プロファイル生成は未実装です。"
        )

    return sk


def extrude_sketch(sketch: cq.Sketch, distance: float) -> cq.Workplane:
    """build_profile()の結果(cq.Sketch)を実際に立体化する。"""
    try:
        return cq.Workplane("XY").placeSketch(sketch).extrude(distance)
    except Exception as e:
        raise SketchError(f"スケッチの押し出しに失敗しました: {e}") from e