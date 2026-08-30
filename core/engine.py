from __future__ import annotations

"""
CAD Core Engine

CADコアエンジン本体。
"""

import cadquery as cq

from dataclasses import dataclass, field
from typing import Any

from .transform import (
    TransformError,
    apply_transform,
)
from .sketch import (
    SketchError,
    build_profile,
    extrude_sketch,
)
from .selection import (
    SelectionError,
    selection,
    resolve_selections,
)

try:
    from cadquery.selectors import Selector as _CQSelector
except ImportError:  # cadqueryのバージョン差異に備えたフォールバック
    from cadquery import Selector as _CQSelector


class _ExactShapeSelector(_CQSelector):
    """
    resolve_selections()で得た特定のEdge/Face個体だけを残すSelector。
    fillet/chamferで「全edgeではなく指定したedgeだけ」を対象にするために使う。
    """

    def __init__(self, wanted):
        self._wanted = list(wanted)

    def filter(self, objectList):
        return [o for o in objectList if any(o.isSame(w) for w in self._wanted)]


class GeometryError(Exception):
    """幾何生成・ブーリアン演算に失敗したときの例外。"""


@dataclass
class BuildResult:
    solid: Any
    volume: float
    face_count: int
    edge_count: int
    warnings: list[str] = field(default_factory=list)


def _build_primitive(prim: dict) -> cq.Workplane:
    ptype = prim.get("type")
    p = prim.get("params", {})

    try:
        if not isinstance(p, dict):
            raise GeometryError(
                f"プリミティブ '{prim.get('id')}' のparamsはオブジェクトで指定してください"
            )

        if ptype == "box":
            # JSON仕様(§5)に合わせて width(X軸) / depth(Y軸) / height(Z軸) を正式採用する。
            shape = cq.Workplane("XY").box(p["width"], p["depth"], p["height"])
            return apply_transform(shape, prim)

        if ptype == "cylinder":
            shape = cq.Workplane("XY").cylinder(p["height"], p["radius"])
            return apply_transform(shape, prim)

        if ptype == "sphere":
            shape = cq.Workplane("XY").sphere(p["radius"])
            return apply_transform(shape, prim)

        if ptype == "cone":
            r1 = p.get("radius1", p.get("radius", 10.0))
            r2 = p.get("radius2", 0.0)
            height = p.get("height", 20.0)
            r2_val = r2 if r2 > 0 else 1e-6
            shape = (
                cq.Workplane("XY")
                .circle(r1)
                .workplane(offset=height)
                .circle(r2_val)
                .loft()
            )
            return apply_transform(shape, prim)

        if ptype == "torus":
            r1 = p.get("radius1", 10.0)
            r2 = p.get("radius2", 2.0)
            # cq.Workplane に .torus() は存在しない(実行して初めて判明したバグ。
            # 前バージョンで発見・修正済みだったが、このtransform.py対応版に再度混入していた)。
            # 正しくは cadquery.occ_impl.shapes.Solid.makeTorus() を使い、
            # それをWorkplaneに包み直してからtransformを適用する。
            from cadquery.occ_impl.shapes import Solid
            solid = Solid.makeTorus(r1, r2)
            shape = cq.Workplane("XY").newObject([solid])
            return apply_transform(shape, prim)

        if ptype == "extrude":
            sketch_shape = p.get("shape", "rectangle")
            distance = p.get("distance", 10.0)
            wp = cq.Workplane("XY")
            if sketch_shape == "rectangle":
                shape = wp.rect(p["length"], p["width"]).extrude(distance)
                return apply_transform(shape, prim)
            elif sketch_shape == "circle":
                shape = wp.circle(p["radius"]).extrude(distance)
                return apply_transform(shape, prim)
            else:
                raise GeometryError(f"未対応のextrudeスケッチ形状: {sketch_shape!r}")

        raise GeometryError(f"未対応のプリミティブ種別: {ptype!r}")

    except GeometryError:
        raise
    except TransformError as e:
        raise GeometryError(str(e)) from e
    except Exception as e:
        raise GeometryError(f"プリミティブ '{ptype}' の構築に失敗しました: {e}") from e


def _resolve_edge_selector(target_shape: cq.Workplane, edge_specs: list) -> _CQSelector:
    """
    operationの"edges"指定(int index、または{"kind":..,"index":..}のdict)を
    selection.pyのSelectionResultへ変換し、実体解決してSelectorにまとめる。
    """
    selections = []
    for spec in edge_specs:
        if isinstance(spec, int):
            selections.append(selection("edge", spec))
        elif isinstance(spec, dict):
            if "index" not in spec:
                raise GeometryError(f"edges指定にindexがありません: {spec!r}")
            selections.append(selection(spec.get("kind", "edge"), spec["index"]))
        else:
            raise GeometryError(f"edges指定の形式が不正です: {spec!r}")

    resolved = resolve_selections(target_shape, selections)
    return _ExactShapeSelector(resolved)


def _apply_operation(shapes: dict[str, cq.Workplane], op: dict, sketches: dict) -> cq.Workplane:
    kind = op.get("op")
    try:
        # -------------------------------------------------
        # extrude: sketch(2Dプロファイル) → Solid
        # 仕様: Sketch → geometry → profile → extrude → Solid
        # -------------------------------------------------
        if kind == "extrude":
            sketch_id = op.get("sketch")
            distance = op.get("distance")
            if sketch_id not in sketches:
                raise GeometryError(f"sketch '{sketch_id}' が見つかりません")
            if distance is None:
                raise GeometryError("extrudeにはdistanceが必要です")
            if distance == 0:
                raise GeometryError("extrudeのdistanceは0以外である必要があります(正:+Z方向、負:-Z方向)")
            try:
                return extrude_sketch(sketches[sketch_id], distance)
            except SketchError as e:
                raise GeometryError(str(e)) from e

        if kind in ("fillet", "chamfer"):
            target_id = op.get("target") or op.get("base")
            if target_id not in shapes:
                raise GeometryError(f"対象形状 '{target_id}' が見つかりません")
            target_shape = shapes[target_id]
            radius = op.get("radius", op.get("distance", 1.0))

            edge_specs = op.get("edges")
            if edge_specs:
                try:
                    edge_selector = _resolve_edge_selector(target_shape, edge_specs)
                except SelectionError as e:
                    raise GeometryError(str(e)) from e
                target_edges = target_shape.edges(edge_selector)
            else:
                # "edges"未指定なら後方互換で全edgeを対象にする(従来の挙動)
                target_edges = target_shape.edges()

            if kind == "fillet":
                return target_edges.fillet(radius)
            else:
                return target_edges.chamfer(radius)

        base_id = op.get("base")
        tool_id = op.get("tool")
        if not base_id or base_id not in shapes:
            raise GeometryError(f"base '{base_id}' が primitives に見つかりません")
        if not tool_id or tool_id not in shapes:
            raise GeometryError(f"tool '{tool_id}' が primitives に見つかりません")

        base = shapes[base_id]
        tool = shapes[tool_id]

        # "subtract"はJSON仕様側の呼び名。engine内部(CadQuery)の"cut"のエイリアスとして扱う。
        if kind in ("cut", "subtract"):
            return base.cut(tool)
        if kind == "union":
            return base.union(tool)
        if kind == "intersect":
            return base.intersect(tool)

        raise GeometryError(f"未対応の演算種別: {kind!r}")

    except GeometryError:
        raise
    except Exception as e:
        raise GeometryError(f"演算 '{kind}' の適用に失敗しました: {e}") from e


def validate_solid(result: cq.Workplane) -> list[str]:
    warnings: list[str] = []
    try:
        solid = result.val()
        if not solid:
            warnings.append("有効な立体(Solid)が生成されていません。")
            return warnings
        volume = solid.Volume()
        if volume <= 0:
            warnings.append(f"体積が0以下です(volume={volume})。ブーリアン演算の順序や形状の重なりを確認してください。")
        faces = result.faces().vals()
        if len(faces) == 0:
            warnings.append("面が1つもありません。形状が破綻している可能性があります。")
    except Exception as e:
        warnings.append(f"バリデーション計算中に例外が発生しました: {e}")
    return warnings


def build_from_dict(param_dict: dict) -> BuildResult:
    units = param_dict.get("units", "mm")
    if units != "mm":
        raise GeometryError(f"現在はunits='mm'のみ対応しています(指定値: {units!r})")

    primitives_def = param_dict.get("primitives", [])
    sketches_def = param_dict.get("sketches", [])
    operations_def = param_dict.get("operations", [])

    if not primitives_def and not sketches_def:
        raise GeometryError("primitives/sketchesが両方空です。最低1つの形状定義が必要です。")

    shapes: dict[str, cq.Workplane] = {}
    sketches: dict[str, cq.Face] = {}  # build_profile()がcq.Faceを返す仕様に変更(sketch.py参照)

    # 0. 全sketchを構築(2Dプロファイルのみ。まだ立体化しない)
    for sdef in sketches_def:
        sid = sdef.get("id")
        if not sid:
            raise GeometryError("sketchにidがありません")
        if sid in sketches:
            raise GeometryError(f"sketch id '{sid}' が重複しています")
        try:
            sketches[sid] = build_profile(sdef)
        except SketchError as e:
            raise GeometryError(str(e)) from e

    # 1. 全プリミティブを構築
    for prim in primitives_def:
        pid = prim.get("id")
        if not pid:
            raise GeometryError("primitiveにidがありません")
        if pid in shapes:
            raise GeometryError(f"primitive id '{pid}' が重複しています")
        shapes[pid] = _build_primitive(prim)

    # 2. 演算処理(extrudeでsketchをshapesに合流させることもある)
    if not operations_def:
        if not shapes:
            raise GeometryError("operationsが無い場合、primitivesが最低1つ必要です(sketchだけではextrudeされません)")
        result_shape = next(iter(shapes.values()))
    else:
        result_shape = None
        for op in operations_def:
            result_shape = _apply_operation(shapes, op, sketches)
            result_id = op.get("result_id")
            if not result_id:
                raise GeometryError(f"operation '{op.get('op')}' にはresult_idが必要です")
            shapes[result_id] = result_shape
        if result_shape is None:
            raise GeometryError("operationsの処理結果がありません")

    warnings = validate_solid(result_shape)

    try:
        solid = result_shape.val()
        volume = round(solid.Volume(), 6)
        face_count = len(result_shape.faces().vals())
        edge_count = len(result_shape.edges().vals())
    except Exception as e:
        raise GeometryError(f"最終形状のプロパティ（体積・面数等）取得に失敗しました: {e}") from e

    return BuildResult(
        solid=result_shape,
        volume=volume,
        face_count=face_count,
        edge_count=edge_count,
        warnings=warnings,
    )


def check_interference(shape_a: cq.Workplane, shape_b: cq.Workplane) -> dict:
    try:
        overlap = shape_a.intersect(shape_b)
        val = overlap.val()
        volume = round(val.Volume(), 6) if val else 0.0
        return {"interferes": volume > 1e-6, "overlap_volume": volume}
    except Exception as e:
        raise GeometryError(f"干渉チェック中にエラーが発生しました: {e}") from e


def export_mesh(result_shape: cq.Workplane, tolerance: float = 0.1) -> dict:
    try:
        solid = result_shape.val()
        vertices, triangles = solid.tessellate(tolerance)
        return {
            "vertices": [[round(v.x, 5), round(v.y, 5), round(v.z, 5)] for v in vertices],
            "triangles": [list(t) for t in triangles],
            "vertex_count": len(vertices),
            "triangle_count": len(triangles),
        }
    except Exception as e:
        raise GeometryError(f"メッシュエクスポート処理に失敗しました: {e}") from e


def export_step(result_shape: cq.Workplane, filepath: str) -> None:
    try:
        cq.exporters.export(result_shape, filepath)
    except Exception as e:
        raise GeometryError(f"STEP出力に失敗しました: {e}") from e


def export_stl(result_shape: cq.Workplane, filepath: str) -> None:
    try:
        cq.exporters.export(result_shape, filepath)
    except Exception as e:
        raise GeometryError(f"STL出力に失敗しました: {e}") from e
