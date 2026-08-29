from __future__ import annotations

"""
CAD Core - Transform / Coordinate System

プリミティブに対する座標変換を担当するモジュール。

設計思想:
- 自然言語やUIを扱わない
- 構造化された position / rotation のみを扱う
- CadQuery の Workplane に対して変換を適用する

座標系:
    position = [x, y, z]
    rotation = [rx, ry, rz]

rotation の単位は degree。

回転の適用順:
    X → Y → Z

その後に position による平行移動を適用する。
"""

from typing import Sequence

import cadquery as cq


class TransformError(Exception):
    """座標変換パラメータが不正、または変換に失敗した場合の例外。"""


DEFAULT_POSITION = (0.0, 0.0, 0.0)
DEFAULT_ROTATION = (0.0, 0.0, 0.0)


def _validate_vector(
    value: Sequence[float],
    name: str,
    primitive_id: str | None = None,
) -> tuple[float, float, float]:
    """
    3要素のベクトルを検証して float の tuple に変換する。
    """

    if not isinstance(value, (list, tuple)):
        prefix = f"primitive '{primitive_id}' " if primitive_id else ""
        raise TransformError(
            f"{prefix}{name}は[x, y, z]形式の配列で指定してください"
        )

    if len(value) != 3:
        prefix = f"primitive '{primitive_id}' " if primitive_id else ""
        raise TransformError(
            f"{prefix}{name}は3要素[x, y, z]で指定してください"
        )

    try:
        return (
            float(value[0]),
            float(value[1]),
            float(value[2]),
        )
    except (TypeError, ValueError) as e:
        prefix = f"primitive '{primitive_id}' " if primitive_id else ""
        raise TransformError(
            f"{prefix}{name}には数値を指定してください"
        ) from e


def get_position(
    prim: dict,
) -> tuple[float, float, float]:
    """
    primitive 定義から position を取得する。

    未指定の場合:
        [0, 0, 0]
    """

    primitive_id = prim.get("id")
    params = prim.get("params", {})

    if not isinstance(params, dict):
        raise TransformError(
            f"primitive '{primitive_id}' のparamsはオブジェクトで指定してください"
        )

    position = params.get("position", DEFAULT_POSITION)

    return _validate_vector(
        position,
        "position",
        primitive_id,
    )


def get_rotation(
    prim: dict,
) -> tuple[float, float, float]:
    """
    primitive 定義から rotation を取得する。

    未指定の場合:
        [0, 0, 0]

    単位:
        degree
    """

    primitive_id = prim.get("id")
    params = prim.get("params", {})

    if not isinstance(params, dict):
        raise TransformError(
            f"primitive '{primitive_id}' のparamsはオブジェクトで指定してください"
        )

    rotation = params.get("rotation", DEFAULT_ROTATION)

    return _validate_vector(
        rotation,
        "rotation",
        primitive_id,
    )


def apply_transform(
    shape: cq.Workplane,
    prim: dict,
) -> cq.Workplane:
    """
    primitive の position / rotation を shape に適用する。

    適用順:
        1. X軸回転
        2. Y軸回転
        3. Z軸回転
        4. 平行移動

    回転中心:
        ワールド原点 (0, 0, 0)

    position:
        [x, y, z] mm

    rotation:
        [rx, ry, rz] degree
    """

    primitive_id = prim.get("id")

    try:
        position = get_position(prim)
        rotation = get_rotation(prim)

        x, y, z = position
        rx, ry, rz = rotation

        result = shape

        # -------------------------------------------------
        # 1. X軸回転
        # -------------------------------------------------
        if rx != 0.0:
            result = result.rotate(
                (0, 0, 0),
                (1, 0, 0),
                rx,
            )

        # -------------------------------------------------
        # 2. Y軸回転
        # -------------------------------------------------
        if ry != 0.0:
            result = result.rotate(
                (0, 0, 0),
                (0, 1, 0),
                ry,
            )

        # -------------------------------------------------
        # 3. Z軸回転
        # -------------------------------------------------
        if rz != 0.0:
            result = result.rotate(
                (0, 0, 0),
                (0, 0, 1),
                rz,
            )

        # -------------------------------------------------
        # 4. 平行移動
        # -------------------------------------------------
        if x != 0.0 or y != 0.0 or z != 0.0:
            result = result.translate(
                (x, y, z),
            )

        return result

    except TransformError:
        raise

    except Exception as e:
        raise TransformError(
            f"primitive '{primitive_id}' の座標変換に失敗しました: {e}"
        ) from e