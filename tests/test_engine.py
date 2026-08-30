import json
from pathlib import Path

import pytest

from cad_core.core.engine import GeometryError, build_from_dict



ROOT = Path(__file__).resolve().parents[1]
SKETCH_DIR = ROOT / "tests" / "sketch"


def load_json(filename: str) -> dict:
    path = SKETCH_DIR / filename
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def test_basic_boolean():
    data = load_json("basic.json")

    result = build_from_dict(data)

    assert result.volume == pytest.approx(25811.240437, abs=1e-6)
    assert result.face_count > 0
    assert result.edge_count > 0


def test_sketch_multi_hole():
    data = load_json("sketch_multi_hole.json")

    result = build_from_dict(data)

    # 60 * 30 - 2 * pi * 3^2
    # = 1743.451332...
    # * 4
    # = 6973.805329...
    assert result.volume == pytest.approx(6973.805329, abs=1e-6)
    assert result.face_count > 0
    assert result.edge_count > 0


def test_zero_extrude_is_rejected():
    data = load_json("err_zero_extrude.json")

    with pytest.raises(GeometryError):
        build_from_dict(data)
# tests/test_engine.py に追記するテスト。
# fillet_single_edge.json を tests/sketch/ に置いてから実行してください。


def test_fillet_single_edge():
    data = load_json("fillet_single_edge.json")

    result = build_from_dict(data)

    # box(30x30x30)のedge0(長さ30)だけをradius=2でfillet。
    # 除去体積 = r^2 * (1 - pi/4) * L = 4 * (1 - pi/4) * 30
    import math
    removed = (2 ** 2) * (1 - math.pi / 4) * 30
    expected_volume = 30 ** 3 - removed

    assert result.volume == pytest.approx(expected_volume, abs=1e-2)
    # 元のbox(face=6, edge=12)より増えているはず(fillet面+新規edge)
    assert result.face_count > 6
    assert result.edge_count > 12


def test_fillet_all_edges_still_works():
    # "edges"未指定時の後方互換(従来の全edge fillet)が壊れていないことを確認。
    data = {
        "primitives": [
            {"id": "box1", "type": "box", "params": {"width": 30, "depth": 30, "height": 30}}
        ],
        "operations": [
            {"op": "fillet", "target": "box1", "radius": 2, "result_id": "box1_filleted"}
        ],
    }

    result = build_from_dict(data)
    assert result.volume > 0
    assert result.face_count > 6

