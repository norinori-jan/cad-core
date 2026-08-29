from __future__ import annotations

"""
core/selection.py

CAD Core - Geometry Selection

Selection 1:
- Solid / Face / Edge / Vertex の取得
- index selection
- topology summary

Selection 2:
- Face / Edge / Vertex の幾何属性取得
- 面種別
- エッジ種別
- 面積
- 長さ
- 中心位置
- 法線
- Bounding Box

設計方針
--------
- 自然言語・UIには依存しない
- engine.py の形状生成責務とは分離する
- 現段階では現在のトポロジーに対する選択を扱う
- index は一時的な参照であり、永続参照とはみなさない
- 将来的な Persistent Reference / Feature Tree を妨げない
"""

from dataclasses import dataclass
from typing import Any

import cadquery as cq


class SelectionError(Exception):
    """ジオメトリ要素の選択に失敗した場合の例外。"""


@dataclass(frozen=True)
class SelectionResult:
    """
    選択結果。

    kind:
        solid / face / edge / vertex

    index:
        現在の Shape 内でのインデックス。

    shape:
        CadQuery / OCCT の実体。
    """

    kind: str
    index: int
    shape: Any


# ============================================================
# Internal helpers
# ============================================================


def _validate_index(index: int, count: int, kind: str) -> None:
    if not isinstance(index, int):
        raise SelectionError(
            f"{kind} indexは整数で指定してください: {index!r}"
        )

    if index < 0 or index >= count:
        raise SelectionError(
            f"{kind} indexが範囲外です: {index} "
            f"(有効範囲: 0..{count - 1})"
        )


def _point_to_dict(point: Any) -> list[float]:
    """CadQuery / OCCT の Point を [x, y, z] に変換する。"""
    return [
        round(float(point.x), 6),
        round(float(point.y), 6),
        round(float(point.z), 6),
    ]


def _vector_to_dict(vector: Any) -> list[float]:
    """CadQuery / OCCT の Vector を [x, y, z] に変換する。"""
    return [
        round(float(vector.x), 6),
        round(float(vector.y), 6),
        round(float(vector.z), 6),
    ]


def _bbox_to_dict(shape: Any) -> dict[str, float]:
    """Shape の Bounding Box を辞書化する。"""
    bbox = shape.BoundingBox()

    return {
        "xmin": round(float(bbox.xmin), 6),
        "ymin": round(float(bbox.ymin), 6),
        "zmin": round(float(bbox.zmin), 6),
        "xmax": round(float(bbox.xmax), 6),
        "ymax": round(float(bbox.ymax), 6),
        "zmax": round(float(bbox.zmax), 6),
    }


def _surface_type(face: Any) -> str:
    """
    Face の幾何学的な種類を取得する。

    CadQuery の Face.geomType() を利用する。
    """

    try:
        return str(face.geomType()).lower()
    except Exception:
        return "unknown"


def _curve_type(edge: Any) -> str:
    """
    Edge の幾何学的な種類を取得する。

    CadQuery の Edge.geomType() を利用する。
    """

    try:
        return str(edge.geomType()).lower()
    except Exception:
        return "unknown"


# ============================================================
# Selection
# ============================================================


def select_solids(shape: cq.Workplane) -> list[SelectionResult]:
    """Workplaneから全Solidを取得する。"""
    try:
        solids = shape.solids().vals()

        return [
            SelectionResult(
                kind="solid",
                index=i,
                shape=solid,
            )
            for i, solid in enumerate(solids)
        ]

    except Exception as e:
        raise SelectionError(
            f"Solid選択に失敗しました: {e}"
        ) from e


def select_faces(shape: cq.Workplane) -> list[SelectionResult]:
    """Workplaneから全Faceを取得する。"""
    try:
        faces = shape.faces().vals()

        return [
            SelectionResult(
                kind="face",
                index=i,
                shape=face,
            )
            for i, face in enumerate(faces)
        ]

    except Exception as e:
        raise SelectionError(
            f"Face選択に失敗しました: {e}"
        ) from e


def select_edges(shape: cq.Workplane) -> list[SelectionResult]:
    """Workplaneから全Edgeを取得する。"""
    try:
        edges = shape.edges().vals()

        return [
            SelectionResult(
                kind="edge",
                index=i,
                shape=edge,
            )
            for i, edge in enumerate(edges)
        ]

    except Exception as e:
        raise SelectionError(
            f"Edge選択に失敗しました: {e}"
        ) from e


def select_vertices(shape: cq.Workplane) -> list[SelectionResult]:
    """Workplaneから全Vertexを取得する。"""
    try:
        vertices = shape.vertices().vals()

        return [
            SelectionResult(
                kind="vertex",
                index=i,
                shape=vertex,
            )
            for i, vertex in enumerate(vertices)
        ]

    except Exception as e:
        raise SelectionError(
            f"Vertex選択に失敗しました: {e}"
        ) from e


def select_solid(
    shape: cq.Workplane,
    index: int = 0,
) -> SelectionResult:
    """指定indexのSolidを取得する。"""
    selections = select_solids(shape)
    _validate_index(index, len(selections), "solid")
    return selections[index]


def select_face(
    shape: cq.Workplane,
    index: int,
) -> SelectionResult:
    """指定indexのFaceを取得する。"""
    selections = select_faces(shape)
    _validate_index(index, len(selections), "face")
    return selections[index]


def select_edge(
    shape: cq.Workplane,
    index: int,
) -> SelectionResult:
    """指定indexのEdgeを取得する。"""
    selections = select_edges(shape)
    _validate_index(index, len(selections), "edge")
    return selections[index]


def select_vertex(
    shape: cq.Workplane,
    index: int,
) -> SelectionResult:
    """指定indexのVertexを取得する。"""
    selections = select_vertices(shape)
    _validate_index(index, len(selections), "vertex")
    return selections[index]


# ============================================================
# Topology summary
# ============================================================


def topology_summary(shape: cq.Workplane) -> dict[str, int]:
    """現在の形状のトポロジー数を返す。"""
    try:
        return {
            "solids": len(shape.solids().vals()),
            "faces": len(shape.faces().vals()),
            "edges": len(shape.edges().vals()),
            "vertices": len(shape.vertices().vals()),
        }

    except Exception as e:
        raise SelectionError(
            f"トポロジー情報の取得に失敗しました: {e}"
        ) from e


# ============================================================
# Geometry information
# ============================================================


def face_info(
    shape: cq.Workplane,
    index: int,
) -> dict[str, Any]:
    """
    指定Faceの幾何属性を返す。

    Returns
    -------
    {
        "kind": "face",
        "index": 0,
        "surface_type": "plane",
        "area": ...,
        "center": [x, y, z],
        "bounding_box": {...}
    }
    """

    selection = select_face(shape, index)
    face = selection.shape

    try:
        center = face.Center()

        return {
            "kind": "face",
            "index": index,
            "surface_type": _surface_type(face),
            "area": round(float(face.Area()), 6),
            "center": _point_to_dict(center),
            "bounding_box": _bbox_to_dict(face),
        }

    except Exception as e:
        raise SelectionError(
            f"Face情報の取得に失敗しました "
            f"(index={index}): {e}"
        ) from e


def edge_info(
    shape: cq.Workplane,
    index: int,
) -> dict[str, Any]:
    """
    指定Edgeの幾何属性を返す。

    Returns
    -------
    {
        "kind": "edge",
        "index": 0,
        "curve_type": "line",
        "length": ...,
        "center": [x, y, z],
        "bounding_box": {...}
    }
    """

    selection = select_edge(shape, index)
    edge = selection.shape

    try:
        center = edge.Center()

        return {
            "kind": "edge",
            "index": index,
            "curve_type": _curve_type(edge),
            "length": round(float(edge.Length()), 6),
            "center": _point_to_dict(center),
            "bounding_box": _bbox_to_dict(edge),
        }

    except Exception as e:
        raise SelectionError(
            f"Edge情報の取得に失敗しました "
            f"(index={index}): {e}"
        ) from e


def vertex_info(
    shape: cq.Workplane,
    index: int,
) -> dict[str, Any]:
    """
    指定Vertexの幾何属性を返す。

    Returns
    -------
    {
        "kind": "vertex",
        "index": 0,
        "position": [x, y, z],
        "bounding_box": {...}
    }
    """

    selection = select_vertex(shape, index)
    vertex = selection.shape

    try:
        position = vertex.Center()

        return {
            "kind": "vertex",
            "index": index,
            "position": _point_to_dict(position),
            "bounding_box": _bbox_to_dict(vertex),
        }

    except Exception as e:
        raise SelectionError(
            f"Vertex情報の取得に失敗しました "
            f"(index={index}): {e}"
        ) from e


# ============================================================
# Bulk geometry inspection
# ============================================================


def inspect_faces(shape: cq.Workplane) -> list[dict[str, Any]]:
    """全Faceの幾何属性を返す。"""
    return [
        face_info(shape, selection.index)
        for selection in select_faces(shape)
    ]


def inspect_edges(shape: cq.Workplane) -> list[dict[str, Any]]:
    """全Edgeの幾何属性を返す。"""
    return [
        edge_info(shape, selection.index)
        for selection in select_edges(shape)
    ]


def inspect_vertices(shape: cq.Workplane) -> list[dict[str, Any]]:
    """全Vertexの幾何属性を返す。"""
    return [
        vertex_info(shape, selection.index)
        for selection in select_vertices(shape)
    ]
# ============================================================
# Face normal / criteria selection
# ============================================================


def face_normal(
    shape: cq.Workplane,
    index: int,
) -> list[float]:
    """
    指定Faceの代表法線を取得する。

    現在はFaceの中心点における法線を取得する。

    Returns
    -------
    [nx, ny, nz]

    Notes
    -----
    平面Faceでは一定の法線になる。
    曲面Faceでは中心位置における局所法線となる。
    """

    selection = select_face(shape, index)
    face = selection.shape

    try:
        center = face.Center()
        normal = face.normalAt(center)

        return _vector_to_dict(normal)

    except Exception as e:
        raise SelectionError(
            f"Face法線の取得に失敗しました "
            f"(index={index}): {e}"
        ) from e


def _vector_matches(
    actual: list[float],
    expected: tuple[float, float, float],
    tolerance: float,
) -> bool:
    """
    2つのベクトルが許容誤差内で一致するか判定する。
    """

    return all(
        abs(actual[i] - expected[i]) <= tolerance
        for i in range(3)
    )


def _normalize_vector(
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    """
    3次元ベクトルを正規化する。
    """

    x, y, z = vector
    length = (x * x + y * y + z * z) ** 0.5

    if length == 0:
        raise SelectionError(
            "法線ベクトルにゼロベクトルは指定できません"
        )

    return (
        x / length,
        y / length,
        z / length,
    )


def select_faces_by_normal(
    shape: cq.Workplane,
    normal: tuple[float, float, float],
    tolerance: float = 1e-6,
) -> list[SelectionResult]:
    """
    指定した法線方向を持つFaceを選択する。

    Parameters
    ----------
    shape:
        対象Workplane

    normal:
        期待する法線方向 [nx, ny, nz]

    tolerance:
        各成分の許容誤差

    Example
    -------
    select_faces_by_normal(
        shape,
        (0, 0, 1)
    )
    """

    try:
        expected = _normalize_vector(normal)

        results: list[SelectionResult] = []

        for selection in select_faces(shape):
            actual = face_normal(shape, selection.index)

            if _vector_matches(
                actual,
                expected,
                tolerance,
            ):
                results.append(selection)

        return results

    except SelectionError:
        raise

    except Exception as e:
        raise SelectionError(
            f"法線方向によるFace選択に失敗しました: {e}"
        ) from e


def select_faces_by_surface_type(
    shape: cq.Workplane,
    surface_type: str,
) -> list[SelectionResult]:
    """
    Surface Type に一致するFaceを選択する。

    Example
    -------
    select_faces_by_surface_type(shape, "plane")
    select_faces_by_surface_type(shape, "cylinder")
    """

    expected = surface_type.lower()

    try:
        results: list[SelectionResult] = []

        for selection in select_faces(shape):
            actual = _surface_type(selection.shape)

            if actual == expected:
                results.append(selection)

        return results

    except Exception as e:
        raise SelectionError(
            f"Surface TypeによるFace選択に失敗しました: {e}"
        ) from e


def select_faces_by_area(
    shape: cq.Workplane,
    min_area: float | None = None,
    max_area: float | None = None,
) -> list[SelectionResult]:
    """
    面積条件に一致するFaceを選択する。

    min_area:
        この値以上

    max_area:
        この値以下
    """

    if min_area is not None and min_area < 0:
        raise SelectionError(
            "min_areaは0以上で指定してください"
        )

    if max_area is not None and max_area < 0:
        raise SelectionError(
            "max_areaは0以上で指定してください"
        )

    if (
        min_area is not None
        and max_area is not None
        and min_area > max_area
    ):
        raise SelectionError(
            "min_areaはmax_area以下で指定してください"
        )

    try:
        results: list[SelectionResult] = []

        for selection in select_faces(shape):
            area = float(selection.shape.Area())

            if min_area is not None and area < min_area:
                continue

            if max_area is not None and area > max_area:
                continue

            results.append(selection)

        return results

    except Exception as e:
        raise SelectionError(
            f"面積によるFace選択に失敗しました: {e}"
        ) from e


def select_faces_by_criteria(
    shape: cq.Workplane,
    surface_type: str | None = None,
    normal: tuple[float, float, float] | None = None,
    min_area: float | None = None,
    max_area: float | None = None,
    tolerance: float = 1e-6,
) -> list[SelectionResult]:
    """
    複数の条件をANDで組み合わせてFaceを選択する。

    Parameters
    ----------
    surface_type:
        plane / cylinder / sphere / cone / torus など

    normal:
        Face中心における法線方向

    min_area:
        最小面積

    max_area:
        最大面積

    tolerance:
        法線比較の許容誤差

    Example
    -------
    上面候補:

        select_faces_by_criteria(
            shape,
            surface_type="plane",
            normal=(0, 0, 1),
        )
    """

    if tolerance < 0:
        raise SelectionError(
            "toleranceは0以上で指定してください"
        )

    try:
        expected_normal = None

        if normal is not None:
            expected_normal = _normalize_vector(normal)

        results: list[SelectionResult] = []

        for selection in select_faces(shape):
            face = selection.shape

            # --------------------------------------------
            # Surface Type
            # --------------------------------------------
            if surface_type is not None:
                actual_surface = _surface_type(face)

                if actual_surface != surface_type.lower():
                    continue

            # --------------------------------------------
            # Area
            # --------------------------------------------
            area = float(face.Area())

            if min_area is not None and area < min_area:
                continue

            if max_area is not None and area > max_area:
                continue

            # --------------------------------------------
            # Normal
            # --------------------------------------------
            if expected_normal is not None:
                actual_normal = face_normal(
                    shape,
                    selection.index,
                )

                if not _vector_matches(
                    actual_normal,
                    expected_normal,
                    tolerance,
                ):
                    continue

            results.append(selection)

        return results

    except SelectionError:
        raise

    except Exception as e:
        raise SelectionError(
            f"Face条件選択に失敗しました: {e}"
        ) from e

# ============================================================
# Edge geometric selection
# ============================================================


def edge_direction(
    shape: cq.Workplane,
    index: int,
) -> list[float]:
    """
    指定Edgeの方向ベクトルを取得する。

    現在は直線Edgeを主対象とする。
    始点 -> 終点方向を正規化して返す。

    Returns
    -------
    [dx, dy, dz]
    """

    selection = select_edge(shape, index)
    edge = selection.shape

    try:
        vertices = edge.Vertices()

        if len(vertices) != 2:
            raise SelectionError(
                f"Edge {index} は直線方向を取得できる"
                f"2頂点Edgeではありません"
            )

        p1 = vertices[0].Center()
        p2 = vertices[1].Center()

        dx = float(p2.x - p1.x)
        dy = float(p2.y - p1.y)
        dz = float(p2.z - p1.z)

        length = (dx * dx + dy * dy + dz * dz) ** 0.5

        if length == 0:
            raise SelectionError(
                f"Edge {index} の長さが0です"
            )

        return [
            dx / length,
            dy / length,
            dz / length,
        ]

    except SelectionError:
        raise

    except Exception as e:
        raise SelectionError(
            f"Edge方向の取得に失敗しました "
            f"(index={index}): {e}"
        ) from e


def _direction_matches(
    actual: list[float],
    expected: tuple[float, float, float],
    tolerance: float,
    bidirectional: bool = True,
) -> bool:
    """
    2つの方向ベクトルが一致するか判定する。

    bidirectional=True の場合、

        (1,0,0)
        (-1,0,0)

    を同じ「X方向」として扱う。

    CADのEdge方向検索では、通常こちらの扱いが便利。
    """

    direct = all(
        abs(actual[i] - expected[i]) <= tolerance
        for i in range(3)
    )

    if direct:
        return True

    if bidirectional:
        reverse = all(
            abs(actual[i] + expected[i]) <= tolerance
            for i in range(3)
        )

        if reverse:
            return True

    return False


def select_edges_by_direction(
    shape: cq.Workplane,
    direction: tuple[float, float, float],
    tolerance: float = 1e-6,
    bidirectional: bool = True,
) -> list[SelectionResult]:
    """
    指定方向のEdgeを選択する。

    Parameters
    ----------
    direction:
        期待する方向。

        例:
            (1, 0, 0) = X方向
            (0, 1, 0) = Y方向
            (0, 0, 1) = Z方向

    tolerance:
        方向比較の許容誤差。

    bidirectional:
        Trueなら正負を同じ方向として扱う。

    Example
    -------
    X方向のEdge:

        select_edges_by_direction(
            shape,
            (1, 0, 0),
        )
    """

    if tolerance < 0:
        raise SelectionError(
            "toleranceは0以上で指定してください"
        )

    try:
        expected = _normalize_vector(direction)
        results: list[SelectionResult] = []

        for selection in select_edges(shape):
            try:
                actual = edge_direction(
                    shape,
                    selection.index,
                )
            except SelectionError:
                # 曲線Edgeなど方向を取得できないEdgeは
                # direction検索から除外する。
                continue

            if _direction_matches(
                actual,
                expected,
                tolerance,
                bidirectional,
            ):
                results.append(selection)

        return results

    except SelectionError:
        raise

    except Exception as e:
        raise SelectionError(
            f"Edge方向による選択に失敗しました: {e}"
        ) from e


def select_edges_by_length(
    shape: cq.Workplane,
    min_length: float | None = None,
    max_length: float | None = None,
) -> list[SelectionResult]:
    """
    Edgeの長さによって選択する。

    min_length:
        この値以上

    max_length:
        この値以下
    """

    if min_length is not None and min_length < 0:
        raise SelectionError(
            "min_lengthは0以上で指定してください"
        )

    if max_length is not None and max_length < 0:
        raise SelectionError(
            "max_lengthは0以上で指定してください"
        )

    if (
        min_length is not None
        and max_length is not None
        and min_length > max_length
    ):
        raise SelectionError(
            "min_lengthはmax_length以下で指定してください"
        )

    try:
        results: list[SelectionResult] = []

        for selection in select_edges(shape):
            length = float(selection.shape.Length())

            if min_length is not None and length < min_length:
                continue

            if max_length is not None and length > max_length:
                continue

            results.append(selection)

        return results

    except Exception as e:
        raise SelectionError(
            f"Edge長さによる選択に失敗しました: {e}"
        ) from e


def select_edges_by_curve_type(
    shape: cq.Workplane,
    curve_type: str,
) -> list[SelectionResult]:
    """
    曲線種別によってEdgeを選択する。

    例:
        line
        circle
        ellipse
        bspline
        bezier
    """

    expected = curve_type.lower()

    try:
        results: list[SelectionResult] = []

        for selection in select_edges(shape):
            actual = selection.shape.geomType().lower()

            if actual == expected:
                results.append(selection)

        return results

    except Exception as e:
        raise SelectionError(
            f"Curve TypeによるEdge選択に失敗しました: {e}"
        ) from e


def select_edges_by_criteria(
    shape: cq.Workplane,
    curve_type: str | None = None,
    direction: tuple[float, float, float] | None = None,
    min_length: float | None = None,
    max_length: float | None = None,
    tolerance: float = 1e-6,
    bidirectional: bool = True,
) -> list[SelectionResult]:
    """
    複数条件をANDで組み合わせてEdgeを選択する。

    Example
    -------
    Z方向の直線Edge:

        select_edges_by_criteria(
            shape,
            curve_type="line",
            direction=(0, 0, 1),
        )

    長さ30mmのZ方向Edge:

        select_edges_by_criteria(
            shape,
            curve_type="line",
            direction=(0, 0, 1),
            min_length=30,
            max_length=30,
            tolerance=1e-6,
        )
    """

    if tolerance < 0:
        raise SelectionError(
            "toleranceは0以上で指定してください"
        )

    if min_length is not None and min_length < 0:
        raise SelectionError(
            "min_lengthは0以上で指定してください"
        )

    if max_length is not None and max_length < 0:
        raise SelectionError(
            "max_lengthは0以上で指定してください"
        )

    if (
        min_length is not None
        and max_length is not None
        and min_length > max_length
    ):
        raise SelectionError(
            "min_lengthはmax_length以下で指定してください"
        )

    try:
        expected_direction = None

        if direction is not None:
            expected_direction = _normalize_vector(direction)

        results: list[SelectionResult] = []

        for selection in select_edges(shape):
            edge = selection.shape

            # --------------------------------------------
            # Curve Type
            # --------------------------------------------
            if curve_type is not None:
                actual_curve = edge.geomType().lower()

                if actual_curve != curve_type.lower():
                    continue

            # --------------------------------------------
            # Length
            # --------------------------------------------
            length = float(edge.Length())

            if min_length is not None:
                if length < min_length:
                    continue

            if max_length is not None:
                if length > max_length:
                    continue

            # --------------------------------------------
            # Direction
            # --------------------------------------------
            if expected_direction is not None:
                try:
                    actual_direction = edge_direction(
                        shape,
                        selection.index,
                    )
                except SelectionError:
                    continue

                if not _direction_matches(
                    actual_direction,
                    expected_direction,
                    tolerance,
                    bidirectional,
                ):
                    continue

            results.append(selection)

        return results

    except SelectionError:
        raise

    except Exception as e:
        raise SelectionError(
            f"Edge条件選択に失敗しました: {e}"
        ) from e
# ============================================================
# Topology relationships
# ============================================================


def face_edges(
    shape: cq.Workplane,
    face_index: int,
) -> list[SelectionResult]:
    """
    指定Faceを構成する境界Edgeを取得する。
    """

    face_selection = select_face(shape, face_index)
    face = face_selection.shape

    try:
        edges = face.Edges()

        results: list[SelectionResult] = []

        all_edges = shape.edges().vals()

        for edge in edges:
            for index, candidate in enumerate(all_edges):
                if edge.isSame(candidate):
                    results.append(
                        select_edge(shape, index)
                    )
                    break

        return results

    except Exception as e:
        raise SelectionError(
            f"Faceの境界Edge取得に失敗しました "
            f"(face_index={face_index}): {e}"
        ) from e


def face_vertices(
    shape: cq.Workplane,
    face_index: int,
) -> list[SelectionResult]:
    """
    指定Faceを構成するVertexを取得する。
    """

    face_selection = select_face(shape, face_index)
    face = face_selection.shape

    try:
        vertices = face.Vertices()

        results: list[SelectionResult] = []

        all_vertices = shape.vertices().vals()

        for vertex in vertices:
            for index, candidate in enumerate(all_vertices):
                if vertex.isSame(candidate):
                    results.append(
                        select_vertex(shape, index)
                    )
                    break

        return results

    except Exception as e:
        raise SelectionError(
            f"FaceのVertex取得に失敗しました "
            f"(face_index={face_index}): {e}"
        ) from e


def edge_faces(
    shape: cq.Workplane,
    edge_index: int,
) -> list[SelectionResult]:
    """
    指定Edgeを共有するFaceを取得する。
    """

    edge_selection = select_edge(shape, edge_index)
    edge = edge_selection.shape

    try:
        results: list[SelectionResult] = []

        all_faces = shape.faces().vals()

        for index, face in enumerate(all_faces):
            for candidate_edge in face.Edges():
                if edge.isSame(candidate_edge):
                    results.append(
                        select_face(shape, index)
                    )
                    break

        return results

    except Exception as e:
        raise SelectionError(
            f"Edgeの隣接Face取得に失敗しました "
            f"(edge_index={edge_index}): {e}"
        ) from e


def edge_vertices(
    shape: cq.Workplane,
    edge_index: int,
) -> list[SelectionResult]:
    """
    指定Edgeの両端Vertexを取得する。
    """

    edge_selection = select_edge(shape, edge_index)
    edge = edge_selection.shape

    try:
        results: list[SelectionResult] = []

        all_vertices = shape.vertices().vals()

        for vertex in edge.Vertices():
            for index, candidate in enumerate(all_vertices):
                if vertex.isSame(candidate):
                    results.append(
                        select_vertex(shape, index)
                    )
                    break

        return results

    except Exception as e:
        raise SelectionError(
            f"EdgeのVertex取得に失敗しました "
            f"(edge_index={edge_index}): {e}"
        ) from e


def vertex_edges(
    shape: cq.Workplane,
    vertex_index: int,
) -> list[SelectionResult]:
    """
    指定Vertexに接続しているEdgeを取得する。
    """

    vertex_selection = select_vertex(shape, vertex_index)
    vertex = vertex_selection.shape

    try:
        results: list[SelectionResult] = []

        all_edges = shape.edges().vals()

        for index, edge in enumerate(all_edges):
            for candidate_vertex in edge.Vertices():
                if vertex.isSame(candidate_vertex):
                    results.append(
                        select_edge(shape, index)
                    )
                    break

        return results

    except Exception as e:
        raise SelectionError(
            f"Vertexの隣接Edge取得に失敗しました "
            f"(vertex_index={vertex_index}): {e}"
        ) from e


def vertex_faces(
    shape: cq.Workplane,
    vertex_index: int,
) -> list[SelectionResult]:
    """
    指定Vertexを共有するFaceを取得する。
    """

    vertex_selection = select_vertex(shape, vertex_index)
    vertex = vertex_selection.shape

    try:
        results: list[SelectionResult] = []

        all_faces = shape.faces().vals()

        for index, face in enumerate(all_faces):
            for candidate_vertex in face.Vertices():
                if vertex.isSame(candidate_vertex):
                    results.append(
                        select_face(shape, index)
                    )
                    break

        return results

    except Exception as e:
        raise SelectionError(
            f"Vertexの隣接Face取得に失敗しました "
            f"(vertex_index={vertex_index}): {e}"
        ) from e
# ============================================================
# Geometric relationships
# ============================================================


def _dot(
    a: list[float],
    b: list[float],
) -> float:
    return (
        a[0] * b[0]
        + a[1] * b[1]
        + a[2] * b[2]
    )


def _cross_length(
    a: list[float],
    b: list[float],
) -> float:
    return (
        (a[1] * b[2] - a[2] * b[1]) ** 2
        + (a[2] * b[0] - a[0] * b[2]) ** 2
        + (a[0] * b[1] - a[1] * b[0]) ** 2
    ) ** 0.5


def faces_parallel(
    shape: cq.Workplane,
    face_a_index: int,
    face_b_index: int,
    tolerance: float = 1e-6,
) -> bool:
    """
    2つのFaceの法線が平行か判定する。
    """

    normal_a = face_normal(shape, face_a_index)
    normal_b = face_normal(shape, face_b_index)

    return _cross_length(normal_a, normal_b) <= tolerance


def faces_perpendicular(
    shape: cq.Workplane,
    face_a_index: int,
    face_b_index: int,
    tolerance: float = 1e-6,
) -> bool:
    """
    2つのFaceの法線が垂直か判定する。
    """

    normal_a = face_normal(shape, face_a_index)
    normal_b = face_normal(shape, face_b_index)

    return abs(_dot(normal_a, normal_b)) <= tolerance


def face_distance(
    shape: cq.Workplane,
    face_a_index: int,
    face_b_index: int,
) -> float:
    """
    2つのFaceの代表点間距離を返す。

    現段階では「厳密な面間最短距離」ではなく、
    各FaceのCenter()間距離を使用する。
    """

    face_a = select_face(shape, face_a_index).shape
    face_b = select_face(shape, face_b_index).shape

    a = face_a.Center()
    b = face_b.Center()

    return (
        (a.x - b.x) ** 2
        + (a.y - b.y) ** 2
        + (a.z - b.z) ** 2
    ) ** 0.5


def edges_parallel(
    shape: cq.Workplane,
    edge_a_index: int,
    edge_b_index: int,
    tolerance: float = 1e-6,
) -> bool:
    """
    2つのEdgeの方向が平行か判定する。
    """

    direction_a = edge_direction(shape, edge_a_index)
    direction_b = edge_direction(shape, edge_b_index)

    return _cross_length(
        direction_a,
        direction_b,
    ) <= tolerance


def edges_perpendicular(
    shape: cq.Workplane,
    edge_a_index: int,
    edge_b_index: int,
    tolerance: float = 1e-6,
) -> bool:
    """
    2つのEdgeの方向が垂直か判定する。
    """

    direction_a = edge_direction(shape, edge_a_index)
    direction_b = edge_direction(shape, edge_b_index)

    return abs(
        _dot(direction_a, direction_b)
    ) <= tolerance


def edge_distance(
    shape: cq.Workplane,
    edge_a_index: int,
    edge_b_index: int,
) -> float:
    """
    2つのEdgeのCenter()間距離を返す。

    現段階では厳密なEdge間最短距離ではなく、
    Center()間距離を使用する。
    """

    edge_a = select_edge(shape, edge_a_index).shape
    edge_b = select_edge(shape, edge_b_index).shape

    a = edge_a.Center()
    b = edge_b.Center()

    return (
        (a.x - b.x) ** 2
        + (a.y - b.y) ** 2
        + (a.z - b.z) ** 2
    ) ** 0.5
def selection(
    kind: str,
    index: int,
) -> SelectionResult:
    """
    SelectionResult を明示的に作成する。

    Parameters
    ----------
    kind:
        solid / face / edge / vertex
    index:
        Shape 内の要素インデックス
    """
    valid_kinds = {"solid", "face", "edge", "vertex"}

    if kind not in valid_kinds:
        raise SelectionError(
            f"未対応のselection種別です: {kind!r}"
        )

    if not isinstance(index, int):
        raise SelectionError(
            f"selection index は整数で指定してください: {index!r}"
        )

    if index < 0:
        raise SelectionError(
            f"selection index は0以上で指定してください: {index}"
        )

    # shape はまだ解決されていないため None。
    # 実体への解決は resolve_selection() で行う。
    return SelectionResult(
        kind=kind,
        index=index,
        shape=None,
    )


def resolve_selection(
    shape: cq.Workplane,
    selected: SelectionResult,
) -> Any:
    """
    SelectionResult を実際の CadQuery / OCCT shape に解決する。

    SelectionResult は kind + index を保持し、
    この関数で対象 Workplane から実体を取得する。
    """

    if not isinstance(selected, SelectionResult):
        raise SelectionError(
            "selected は SelectionResult で指定してください"
        )

    try:
        if selected.kind == "solid":
            return select_solid(
                shape,
                selected.index,
            ).shape

        if selected.kind == "face":
            return select_face(
                shape,
                selected.index,
            ).shape

        if selected.kind == "edge":
            return select_edge(
                shape,
                selected.index,
            ).shape

        if selected.kind == "vertex":
            return select_vertex(
                shape,
                selected.index,
            ).shape

        raise SelectionError(
            f"未対応のselection種別です: {selected.kind!r}"
        )

    except SelectionError:
        raise

    except Exception as e:
        raise SelectionError(
            f"selectionの解決に失敗しました: {e}"
        ) from e


def resolve_selections(
    shape: cq.Workplane,
    selections: list[SelectionResult],
) -> list[Any]:
    """
    複数の SelectionResult を実体へ解決する。
    """

    if not isinstance(selections, list):
        raise SelectionError(
            "selections は SelectionResult のリストで指定してください"
        )

    return [
        resolve_selection(shape, selected)
        for selected in selections
    ]
def select_face_for_operation(
    shape: cq.Workplane,
    index: int,
) -> Any:
    """
    加工処理に渡すための Face を取得する。

    SelectionResult を経由して、実際の CadQuery / OCCT Face を返す。
    """
    selected = selection("face", index)
    return resolve_selection(shape, selected)


def select_edge_for_operation(
    shape: cq.Workplane,
    index: int,
) -> Any:
    """
    加工処理に渡すための Edge を取得する。

    SelectionResult を経由して、実際の CadQuery / OCCT Edge を返す。
    """
    selected = selection("edge", index)
    return resolve_selection(shape, selected)


def select_vertex_for_operation(
    shape: cq.Workplane,
    index: int,
) -> Any:
    """
    加工処理に渡すための Vertex を取得する。

    SelectionResult を経由して、実際の CadQuery / OCCT Vertex を返す。
    """
    selected = selection("vertex", index)
    return resolve_selection(shape, selected)  