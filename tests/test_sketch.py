import json
from pathlib import Path

import pytest

from cad_core.core.sketch import SketchError, build_profile, extrude_sketch



ROOT = Path(__file__).resolve().parents[1]
SKETCH_DIR = ROOT / "tests" / "sketch"


def load_json(filename: str) -> dict:
    path = SKETCH_DIR / filename
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def get_sketch(filename: str) -> dict:
    data = load_json(filename)

    sketches = data.get("sketches", [])
    if not sketches:
        raise AssertionError(f"{filename} にsketch定義がありません")

    return sketches[0]


def test_basic_rectangle_profile():
    data = {
        "plane": "XY",
        "geometry": [
            {
                "type": "rectangle",
                "center": [0, 0],
                "width": 40,
                "height": 30,
            }
        ],
    }

    face = build_profile(data)

    assert face is not None
    assert face.Area() == pytest.approx(1200.0)


def test_multi_hole_profile():
    sketch = get_sketch("sketch_multi_hole.json")

    face = build_profile(sketch)

    expected_area = 60 * 30 - 2 * 3.141592653589793 * 3**2

    assert face.Area() == pytest.approx(expected_area, abs=1e-6)


def test_line_arc_profile():
    sketch = get_sketch("sketch_line_arc_dshape.json")

    face = build_profile(sketch)

    assert face is not None
    assert face.Area() > 0


def test_arc_wraparound_profile():
    sketch = get_sketch("sketch_arc_wraparound.json")

    face = build_profile(sketch)

    assert face is not None
    assert face.Area() > 0


def test_rect_hole_rect_profile():
    sketch = get_sketch("sketch_rect_hole_rect.json")

    face = build_profile(sketch)

    assert face is not None
    assert face.Area() > 0


def test_open_line_is_rejected():
    data = load_json("err_open_line.json")

    sketch = data.get("sketches", [])
    if not sketch:
        pytest.fail("err_open_line.json にsketch定義がありません")

    with pytest.raises(SketchError):
        build_profile(sketch[0])


def test_nested_island_is_rejected():
    data = load_json("err_nested_island.json")

    sketch = data.get("sketches", [])
    if not sketch:
        pytest.fail("err_nested_island.json にsketch定義がありません")

    with pytest.raises(SketchError):
        build_profile(sketch[0])


def test_degenerate_polygon_is_rejected():
    data = load_json("err_degenerate_polygon.json")

    sketch = data.get("sketches", [])
    if not sketch:
        pytest.fail("err_degenerate_polygon.json にsketch定義がありません")

    with pytest.raises(SketchError):
        build_profile(sketch[0])


def test_zero_radius_is_rejected():
    data = load_json("err_zero_radius.json")

    sketch = data.get("sketches", [])
    if not sketch:
        pytest.fail("err_zero_radius.json にsketch定義がありません")

    with pytest.raises(SketchError):
        build_profile(sketch[0])


def test_extrude_profile():
    sketch = {
        "plane": "XY",
        "geometry": [
            {
                "type": "rectangle",
                "center": [0, 0],
                "width": 40,
                "height": 30,
            }
        ],
    }

    face = build_profile(sketch)
    result = extrude_sketch(face, 15)

    assert result.val().Volume() == pytest.approx(18000.0)
    assert len(result.faces().vals()) == 6
    assert len(result.edges().vals()) == 12
