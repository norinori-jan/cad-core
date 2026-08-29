"""
core/engine.py
======================================================================

CAD Core Engine

構造化されたCADパラメータ辞書を受け取り、
CadQuery / OpenCASCADE を使用して3D形状を生成する。

設計思想
----------------------------------------------------------------------
- 自然言語を扱わない
- UIを扱わない
- AIを扱わない
- JSONで表現された構造化CAD定義だけを受け取る
- 座標変換は core.transform に委譲する
- 幾何計算は CadQuery / OCCT に委譲する

入力
----------------------------------------------------------------------
{
    "units": "mm",
    "primitives": [...],
    "operations": [...]
}

Primitive
----------------------------------------------------------------------
box
cylinder
sphere
cone
torus
extrude

Operation
----------------------------------------------------------------------
union
subtract
cut
intersect
fillet
chamfer

Transform
----------------------------------------------------------------------
position = [x, y, z]
rotation = [rx, ry, rz]

rotation:
    degree

適用順:
    X -> Y -> Z -> translation

実際の幾何計算:
    CadQuery -> OpenCASCADE (OCCT / C++)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cadquery as cq

from .transform import TransformError
from .transform import apply_transform


# ======================================================================
# Exceptions
# ======================================================================


class GeometryError(Exception):
    """
    CAD形状生成・変換・Boolean・加工などに失敗した場合の例外。
    """


# ======================================================================
# Result
# ======================================================================


@dataclass
class BuildResult:
    """
    CAD生成結果。

    solid:
        最終的な CadQuery Workplane

    volume:
        体積 mm^3

    face_count:
        面数

    edge_count:
        エッジ数

    warnings:
        形状自体は生成できたが注意が必要な事項
    """

    solid: Any
    volume: float
    face_count: int
    edge_count: int
    warnings: list[str] = field(default_factory=list)


# ======================================================================
# Helpers
# ======================================================================


def _get_params(prim: dict) -> dict:
    """
    primitive.params を取得する。

    params が存在しない、またはdictでない場合は GeometryError。
    """

    primitive_id = prim.get("id")

    params = prim.get("params", {})

    if not isinstance(params, dict):
        raise GeometryError(
            f"primitive '{primitive_id}' のparamsはオブジェクトで指定してください"
        )

    return params


def _apply_primitive_transform(
    shape: cq.Workplane,
    prim: dict,
) -> cq.Workplane:
    """
    primitive に position / rotation を適用する。

    実際の処理は core.transform に委譲する。

    engine.py は座標変換アルゴリズムを持たない。
    """

    try:
        return apply_transform(shape, prim)

    except TransformError as e:
        raise GeometryError(str(e)) from e

    except Exception as e:
        primitive_id = prim.get("id")

        raise GeometryError(
            f"primitive '{primitive_id}' の座標変換に失敗しました: {e}"
        ) from e


# ======================================================================
# Primitive Builders
# ======================================================================


def _build_primitive(prim: dict) -> cq.Workplane:
    """
    1つのprimitive定義からCadQuery Workplaneを生成する。

    JSON仕様:
        box
        cylinder
        sphere
        cone
        torus
        extrude
    """

    primitive_id = prim.get("id")
    ptype = prim.get("type")

    if not ptype:
        raise GeometryError(
            f"primitive '{primitive_id}' にtypeがありません"
        )

    try:
        params = _get_params(prim)

        # --------------------------------------------------------------
        # BOX
        # --------------------------------------------------------------
        #
        # 正式JSON:
        #
        #   width
        #   depth
        #   height
        #
        # 旧形式:
        #
        #   length
        #   width
        #   height
        #
        # の両方を受け付ける。
        #
        if ptype == "box":

            if "width" not in params:
                raise GeometryError(
                    f"box '{primitive_id}' にwidthがありません"
                )

            if "depth" in params:
                width = params["width"]
                depth = params["depth"]

            elif "length" in params:
                # 旧仕様との互換性
                width = params["length"]
                depth = params["width"]

            else:
                raise GeometryError(
                    f"box '{primitive_id}' にdepthがありません"
                )

            if "height" not in params:
                raise GeometryError(
                    f"box '{primitive_id}' にheightがありません"
                )

            shape = (
                cq.Workplane("XY")
                .box(
                    width,
                    depth,
                    params["height"],
                )
            )

            return _apply_primitive_transform(shape, prim)

        # --------------------------------------------------------------
        # CYLINDER
        # --------------------------------------------------------------

        if ptype == "cylinder":

            if "radius" not in params:
                raise GeometryError(
                    f"cylinder '{primitive_id}' にradiusがありません"
                )

            if "height" not in params:
                raise GeometryError(
                    f"cylinder '{primitive_id}' にheightがありません"
                )

            shape = (
                cq.Workplane("XY")
                .cylinder(
                    params["height"],
                    params["radius"],
                )
            )

            return _apply_primitive_transform(shape, prim)

        # --------------------------------------------------------------
        # SPHERE
        # --------------------------------------------------------------

        if ptype == "sphere":

            if "radius" not in params:
                raise GeometryError(
                    f"sphere '{primitive_id}' にradiusがありません"
                )

            shape = (
                cq.Workplane("XY")
                .sphere(params["radius"])
            )

            return _apply_primitive_transform(shape, prim)

        # --------------------------------------------------------------
        # CONE
        # --------------------------------------------------------------
        #
        # radius1:
        #     下側半径
        #
        # radius2:
        #     上側半径
        #
        # radius2 == 0 の場合は極小値にしてloft。
        #
        if ptype == "cone":

            radius1 = params.get(
                "radius1",
                params.get("radius", 10.0),
            )

            radius2 = params.get(
                "radius2",
                0.0,
            )

            height = params.get(
                "height",
                20.0,
            )

            if radius1 <= 0:
                raise GeometryError(
                    f"cone '{primitive_id}' のradius1は0より大きくしてください"
                )

            if radius2 < 0:
                raise GeometryError(
                    f"cone '{primitive_id}' のradius2は0以上にしてください"
                )

            if height <= 0:
                raise GeometryError(
                    f"cone '{primitive_id}' のheightは0より大きくしてください"
                )

            # OCCT/CadQueryのloftで完全な頂点半径0を避ける。
            radius2_value = (
                radius2
                if radius2 > 0
                else 1e-6
            )

            shape = (
                cq.Workplane("XY")
                .circle(radius1)
                .workplane(offset=height)
                .circle(radius2_value)
                .loft()
            )

            return _apply_primitive_transform(shape, prim)

        # --------------------------------------------------------------
        # TORUS
        # --------------------------------------------------------------
        #
        # 正式JSON:
        #
        #   radius_major
        #   radius_minor
        #
        # 旧仕様:
        #
        #   radius1
        #   radius2
        #
        # を両方受け付ける。
        #
        # 重要:
        #   cq.Workplane().torus() は使用しない。
        #
        #   CadQueryのSolid.makeTorus()を使用する。
        #
        if ptype == "torus":

            radius_major = params.get(
                "radius_major",
                params.get("radius1", 10.0),
            )

            radius_minor = params.get(
                "radius_minor",
                params.get("radius2", 2.0),
            )

            if radius_major <= 0:
                raise GeometryError(
                    f"torus '{primitive_id}' のradius_majorは0より大きくしてください"
                )

            if radius_minor <= 0:
                raise GeometryError(
                    f"torus '{primitive_id}' のradius_minorは0より大きくしてください"
                )

            if radius_minor >= radius_major:
                raise GeometryError(
                    f"torus '{primitive_id}' はradius_minor < radius_majorで指定してください"
                )

            from cadquery.occ_impl.shapes import Solid

            solid = Solid.makeTorus(
                radius_major,
                radius_minor,
            )

            shape = (
                cq.Workplane("XY")
                .newObject([solid])
            )

            return _apply_primitive_transform(shape, prim)

        # --------------------------------------------------------------
        # EXTRUDE
        # --------------------------------------------------------------

        if ptype == "extrude":

            sketch_shape = params.get(
                "shape",
                "rectangle",
            )

            distance = params.get(
                "distance",
                10.0,
            )

            if distance <= 0:
                raise GeometryError(
                    f"extrude '{primitive_id}' のdistanceは0より大きくしてください"
                )

            wp = cq.Workplane("XY")

            # ----------------------------------------------------------
            # rectangle
            # ----------------------------------------------------------

            if sketch_shape == "rectangle":

                if "length" not in params:
                    raise GeometryError(
                        f"extrude '{primitive_id}' のrectangleにlengthがありません"
                    )

                if "width" not in params:
                    raise GeometryError(
                        f"extrude '{primitive_id}' のrectangleにwidthがありません"
                    )

                shape = (
                    wp
                    .rect(
                        params["length"],
                        params["width"],
                    )
                    .extrude(distance)
                )

                return _apply_primitive_transform(shape, prim)

            # ----------------------------------------------------------
            # circle
            # ----------------------------------------------------------

            if sketch_shape == "circle":

                if "radius" not in params:
                    raise GeometryError(
                        f"extrude '{primitive_id}' のcircleにradiusがありません"
                    )

                shape = (
                    wp
                    .circle(params["radius"])
                    .extrude(distance)
                )

                return _apply_primitive_transform(shape, prim)

            raise GeometryError(
                f"未対応のextrudeスケッチ形状: {sketch_shape!r}"
            )

        # --------------------------------------------------------------
        # UNKNOWN
        # --------------------------------------------------------------

        raise GeometryError(
            f"未対応のプリミティブ種別: {ptype!r}"
        )

    except GeometryError:
        raise

    except Exception as e:
        raise GeometryError(
            f"プリミティブ '{primitive_id}' ({ptype}) の構築に失敗しました: {e}"
        ) from e


# ======================================================================
# Operations
# ======================================================================


def _apply_operation(
    shapes: dict[str, cq.Workplane],
    op: dict,
) -> cq.Workplane:
    """
    1つのoperationを適用する。

    対応:
        union
        subtract
        cut
        intersect
        fillet
        chamfer
    """

    kind = op.get("op")

    if not kind:
        raise GeometryError(
            "operationにopがありません"
        )

    try:

        # ==============================================================
        # FILLET / CHAMFER
        # ==============================================================

        if kind in ("fillet", "chamfer"):

            target_id = (
                op.get("target")
                or op.get("base")
            )

            if not target_id:
                raise GeometryError(
                    f"{kind} operationにtargetがありません"
                )

            if target_id not in shapes:
                raise GeometryError(
                    f"対象形状 '{target_id}' が見つかりません"
                )

            target_shape = shapes[target_id]

            if kind == "fillet":

                radius = op.get(
                    "radius",
                    1.0,
                )

                if radius <= 0:
                    raise GeometryError(
                        "filletのradiusは0より大きくしてください"
                    )

                return (
                    target_shape
                    .edges()
                    .fillet(radius)
                )

            # chamfer

            distance = op.get(
                "distance",
                op.get("radius", 1.0),
            )

            if distance <= 0:
                raise GeometryError(
                    "chamferのdistanceは0より大きくしてください"
                )

            return (
                target_shape
                .edges()
                .chamfer(distance)
            )

        # ==============================================================
        # BOOLEAN
        # ==============================================================

        base_id = op.get("base")
        tool_id = op.get("tool")

        if not base_id:
            raise GeometryError(
                f"operation '{kind}' にbaseがありません"
            )

        if not tool_id:
            raise GeometryError(
                f"operation '{kind}' にtoolがありません"
            )

        if base_id not in shapes:
            raise GeometryError(
                f"base '{base_id}' が形状一覧に見つかりません"
            )

        if tool_id not in shapes:
            raise GeometryError(
                f"tool '{tool_id}' が形状一覧に見つかりません"
            )

        base = shapes[base_id]
        tool = shapes[tool_id]

        # --------------------------------------------------------------
        # UNION
        # --------------------------------------------------------------

        if kind == "union":

            return base.union(tool)

        # --------------------------------------------------------------
        # SUBTRACT
        # --------------------------------------------------------------
        #
        # 現在のJSON仕様は subtract。
        #
        # CadQuery APIではcutを使用する。
        #
        # cutも後方互換として許可する。
        #
        if kind in ("subtract", "cut"):

            return base.cut(tool)

        # --------------------------------------------------------------
        # INTERSECT
        # --------------------------------------------------------------

        if kind == "intersect":

            return base.intersect(tool)

        # --------------------------------------------------------------
        # UNKNOWN
        # --------------------------------------------------------------

        raise GeometryError(
            f"未対応の演算種別: {kind!r}"
        )

    except GeometryError:
        raise

    except Exception as e:
        raise GeometryError(
            f"演算 '{kind}' の適用に失敗しました: {e}"
        ) from e


# ======================================================================
# Validation
# ======================================================================


def validate_solid(
    result: cq.Workplane,
) -> list[str]:
    """
    最終形状の最低限のバリデーション。

    ここでは「失敗」ではなく「warning」として扱えるものを返す。
    """

    warnings: list[str] = []

    if result is None:
        warnings.append(
            "最終形状が生成されていません。"
        )
        return warnings

    try:

        solid = result.val()

        if not solid:
            warnings.append(
                "有効な立体(Solid)が生成されていません。"
            )
            return warnings

        # --------------------------------------------------------------
        # Volume
        # --------------------------------------------------------------

        volume = solid.Volume()

        if volume <= 0:
            warnings.append(
                "体積が0以下です "
                f"(volume={volume})。"
                "Boolean演算の順序や形状の重なりを確認してください。"
            )

        # --------------------------------------------------------------
        # Faces
        # --------------------------------------------------------------

        faces = result.faces().vals()

        if len(faces) == 0:
            warnings.append(
                "面が1つもありません。"
                "形状が破綻している可能性があります。"
            )

    except Exception as e:

        warnings.append(
            f"バリデーション計算中に例外が発生しました: {e}"
        )

    return warnings


# ======================================================================
# Build
# ======================================================================


def build_from_dict(
    param_dict: dict,
) -> BuildResult:
    """
    構造化されたCADパラメータ辞書から最終形状を生成する。

    Parameters
    ----------
    param_dict:
        JSONから読み込んだdict。

    Returns
    -------
    BuildResult
        最終形状とメタデータ。

    Example
    -------
    {
        "units": "mm",
        "primitives": [
            {
                "id": "box",
                "type": "box",
                "params": {
                    "width": 40,
                    "depth": 30,
                    "height": 20,
                    "position": [10, 0, 0],
                    "rotation": [0, 0, 45]
                }
            }
        ]
    }
    """

    if not isinstance(param_dict, dict):
        raise GeometryError(
            "CADパラメータはJSONオブジェクト(dict)で指定してください"
        )

    primitives_def = param_dict.get(
        "primitives",
        [],
    )

    operations_def = param_dict.get(
        "operations",
        [],
    )

    # ==============================================================
    # Input validation
    # ==============================================================

    if not isinstance(primitives_def, list):
        raise GeometryError(
            "primitivesは配列で指定してください"
        )

    if not isinstance(operations_def, list):
        raise GeometryError(
            "operationsは配列で指定してください"
        )

    if not primitives_def:
        raise GeometryError(
            "primitivesが空です。最低1つの形状定義が必要です。"
        )

    # ==============================================================
    # Build primitives
    # ==============================================================

    shapes: dict[str, cq.Workplane] = {}

    for prim in primitives_def:

        if not isinstance(prim, dict):
            raise GeometryError(
                "primitiveはオブジェクトで指定してください"
            )

        primitive_id = prim.get("id")

        if not primitive_id:
            raise GeometryError(
                "primitiveにidがありません"
            )

        if primitive_id in shapes:
            raise GeometryError(
                f"primitive id '{primitive_id}' が重複しています"
            )

        shapes[primitive_id] = _build_primitive(
            prim
        )

    # ==============================================================
    # Apply operations
    # ==============================================================

    if not operations_def:

        # operationがない場合、
        # 最初のprimitiveを最終形状とする。
        result_shape = next(
            iter(shapes.values())
        )

    else:

        result_shape: cq.Workplane | None = None

        for index, op in enumerate(operations_def):

            if not isinstance(op, dict):
                raise GeometryError(
                    f"operation[{index}]はオブジェクトで指定してください"
                )

            result_shape = _apply_operation(
                shapes,
                op,
            )

            result_id = op.get(
                "result_id"
            )

            if result_id:

                if result_id in shapes:
                    raise GeometryError(
                        f"operation[{index}]: "
                        f"result_id '{result_id}' は既に存在します"
                    )

                shapes[result_id] = result_shape

        if result_shape is None:
            raise GeometryError(
                "operationsは存在しますが、最終形状が生成されませんでした"
            )

    # ==============================================================
    # Validation
    # ==============================================================

    warnings = validate_solid(
        result_shape
    )

    # ==============================================================
    # Properties
    # ==============================================================

    try:

        solid = result_shape.val()

        if not solid:
            raise GeometryError(
                "最終形状のSolidを取得できません"
            )

        volume = round(
            solid.Volume(),
            6,
        )

        face_count = len(
            result_shape
            .faces()
            .vals()
        )

        edge_count = len(
            result_shape
            .edges()
            .vals()
        )

    except GeometryError:
        raise

    except Exception as e:

        raise GeometryError(
            "最終形状のプロパティ "
            "(体積・面数・エッジ数等) "
            f"取得に失敗しました: {e}"
        ) from e

    return BuildResult(
        solid=result_shape,
        volume=volume,
        face_count=face_count,
        edge_count=edge_count,
        warnings=warnings,
    )


# ======================================================================
# Interference
# ======================================================================


def check_interference(
    shape_a: cq.Workplane,
    shape_b: cq.Workplane,
) -> dict:
    """
    2つの形状の干渉をチェックする。

    shape_a ∩ shape_b を計算し、
    重複体積が 1e-6 mm^3 を超える場合に
    interferes=True とする。
    """

    try:

        overlap = shape_a.intersect(
            shape_b
        )

        val = overlap.val()

        if val:

            volume = round(
                val.Volume(),
                6,
            )

        else:

            volume = 0.0

        return {
            "interferes": volume > 1e-6,
            "overlap_volume": volume,
        }

    except Exception as e:

        raise GeometryError(
            f"干渉チェック中にエラーが発生しました: {e}"
        ) from e


# ======================================================================
# Mesh Export
# ======================================================================


def export_mesh(
    result_shape: cq.Workplane,
    tolerance: float = 0.1,
) -> dict:
    """
    CAD形状を軽量三角形メッシュへ変換する。

    Three.js等の外部表示側へ渡すことを想定。

    tolerance:
        メッシュ化精度。
    """

    try:

        solid = result_shape.val()

        if not solid:
            raise GeometryError(
                "メッシュ化対象のSolidを取得できません"
            )

        vertices, triangles = (
            solid.tessellate(tolerance)
        )

        return {
            "vertices": [
                [
                    round(v.x, 5),
                    round(v.y, 5),
                    round(v.z, 5),
                ]
                for v in vertices
            ],
            "triangles": [
                list(t)
                for t in triangles
            ],
            "vertex_count": len(vertices),
            "triangle_count": len(triangles),
        }

    except GeometryError:
        raise

    except Exception as e:

        raise GeometryError(
            f"メッシュエクスポート処理に失敗しました: {e}"
        ) from e


# ======================================================================
# STEP Export
# ======================================================================


def export_step(
    result_shape: cq.Workplane,
    filepath: str,
) -> None:
    """
    STEPファイルへ出力する。
    """

    try:

        cq.exporters.export(
            result_shape,
            filepath,
        )

    except Exception as e:

        raise GeometryError(
            f"STEP出力に失敗しました: {e}"
        ) from e


# ======================================================================
# STL Export
# ======================================================================


def export_stl(
    result_shape: cq.Workplane,
    filepath: str,
) -> None:
    """
    STLファイルへ出力する。
    """

    try:

        cq.exporters.export(
            result_shape,
            filepath,
        )

    except Exception as e:

        raise GeometryError(
            f"STL出力に失敗しました: {e}"
        ) from e