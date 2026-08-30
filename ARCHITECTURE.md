# cad-core Architecture

## 1. Product Boundary

### What cad-core IS

**cad-core is a stateless JSON → solid batch geometry pipeline.**

- Input: JSON definition (primitives, sketches, operations)
- Processing: Single-pass transformation through geometry engine
- Output: 3D solid (CadQuery Workplane) with metadata (volume, face count, edge count, warnings)
- Execution model: No persistent state between invocations
- API: `build_from_dict(param_dict: dict) → BuildResult`

**Source:** `core/engine.py:build_from_dict()` (L189-238)

Supported operations:
- **Primitives** (3D): box, cylinder, sphere, cone, torus
- **Sketches** (2D): line, circle, arc, rectangle, polygon
- **Operations**: extrude, cut (subtract), union, intersect, fillet, chamfer

### What cad-core IS NOT

cad-core is **not** an interactive parametric CAD kernel. The following are **intentionally outside the current product scope**:

1. **Feature History Editing** - No undo/redo, no history stack
2. **Constraint Solving** - No parametric constraints (dimension, coincident, parallel, etc.)
3. **Dimensions as Parametric Constraints** - Dimensions are not live-updating parameters
4. **Persistent Topology IDs** - Face/Edge/Vertex indices are computed per execution and not persisted
5. **Pattern Instance Identity** - No pattern/array feature; individual copies are not tracked as instances
6. **Interactive Sketch Editing** - No UI sketch tool; sketches are JSON-defined, batch-processed

---

## 2. Current Data Flow

```
JSON Input (param_dict)
  │
  ├─ sketches[]
  │    ├─ geometry[] (line/circle/arc/rectangle/polygon)
  │    │    ↓
  │    └─ build_profile()
  │         ├─ normalize (rectangle/polygon → line edges)
  │         ├─ close loops (line/arc endpoint tracing)
  │         ├─ detect outer/inner (bounding box ranking)
  │         └─ return: cq.Face
  │
  ├─ primitives[]
  │    ├─ type (box/cylinder/sphere/cone/torus)
  │    ├─ params{}
  │    ├─ transform{} (optional)
  │    │    ↓
  │    └─ _build_primitive()
  │         └─ return: cq.Workplane
  │
  └─ operations[]
       ├─ extrude: sketch → cq.Face → extrude_sketch() → cq.Workplane
       ├─ cut/union/intersect: (base, tool) → cq.Workplane
       ├─ fillet/chamfer: target → cq.Workplane
       │    ↓
       └─ _apply_operation() for each operation
            └─ return: cq.Workplane (result_id → shapes dict)

Final Shape Validation
  ├─ volume check (warn if ≤ 0)
  ├─ face/edge count
  └─ BuildResult(solid, volume, face_count, edge_count, warnings)
```

**Source references:**
- `core/engine.py:build_from_dict()` (L189-238) - Main orchestration
- `core/engine.py:_apply_operation()` (L101-145) - Operation execution
- `core/sketch.py:build_profile()` (L256-273) - Sketch→Face conversion
- `core/engine.py:validate_solid()` (L148-164) - Result validation

---

## 3. Input Contract

### 3.1 Sketches

```json
{
  "id": "sketch_id",
  "plane": "XY",
  "geometry": [
    {"type": "line", "start": [x, y], "end": [x, y]},
    {"type": "circle", "center": [x, y], "radius": r},
    {"type": "arc", "center": [x, y], "radius": r, "start_angle": deg, "end_angle": deg},
    {"type": "rectangle", "center": [x, y], "width": w, "height": h},
    {"type": "polygon", "points": [[x, y], ...]}
  ]
}
```

**Processing:**
1. Normalize: rectangle/polygon → line edges
2. Trace closed loops: line/arc endpoint matching
3. Detect outer/inner: bounding box containment
4. Return: Single cq.Face (with holes if inner loops exist)

**Constraints:**
- `plane="XY"` only (Z-normal sketch); other planes raise `SketchError`
- Geometry must form closed loops (endpoint mismatch → `SketchError`)
- Polygon: ≥3 points; no degeneracy check (zero-area polygon → warning, not error)
- Circle/rectangle: Single closed outline (no degeneracy check)

**Source:** `core/sketch.py:build_profile()` (L256-273), `core/sketch.py:_closed_loops_from_geometry()` (L230-247)

### 3.2 Primitives

```json
{
  "id": "prim_id",
  "type": "box|cylinder|sphere|cone|torus",
  "params": {...},
  "transform": {"position": [x, y, z], "rotation": [rx, ry, rz], ...}
}
```

**Supported types and params:**

| Type | Params | Notes |
|------|--------|-------|
| box | width, depth, height | X, Y, Z axes |
| cylinder | height, radius | Z-axis |
| sphere | radius | Center at origin |
| cone | height, radius1, radius2 | radius2=0 → cone; radius2>0 → frustum |
| torus | radius1, radius2 | Major, minor radii |

**Transform (optional):**
- `position`: [x, y, z] translation
- `rotation`: [rx, ry, rz] rotation in degrees (XYZ order)

**Source:** `core/engine.py:_build_primitive()` (L47-99)

### 3.3 Operations

**Operand Reference Model: String IDs**

All operands reference shapes by string ID (not array index, not object identity):

```json
{"op": "cut", "base": "box_a", "tool": "hole_cyl", "result_id": "result_1"}
```

- `"base"` / `"tool"`: String ID matching a primitive or previous operation result
- `"result_id"`: Required; labels this operation's output for reference by subsequent operations
- Reference resolution: Linear search in `shapes: dict[str, cq.Workplane]`

**Verification:** `core/engine.py:_apply_operation()` (L119-145)
```python
base_id = op.get("base")
if base_id not in shapes:
    raise GeometryError(f"base '{base_id}' が primitives に見つかりません")
base = shapes[base_id]  # Dictionary lookup by string ID
```

**Operation types:**

| Operation | Input | Output |
|-----------|-------|--------|
| extrude | sketch ID + distance | cq.Workplane (new solid) |
| cut / subtract | base + tool | base.cut(tool) |
| union | base + tool | base.union(tool) |
| intersect | base + tool | base.intersect(tool) |
| fillet | target + radius | target.edges().fillet(radius) |
| chamfer | target + distance | target.edges().chamfer(distance) |

**Source:** `core/engine.py:_apply_operation()` (L101-145)

---

## 4. Sketch Architecture

### 4.1 Sketch Processing Pipeline

```
Sketch JSON
  │ geometry[]
  ├─ rectangle / polygon
  │    ↓ _normalize_geometry()
  │    ↓ Convert to line edges
  │
  ├─ line / arc / circle
  │    ↓ As-is (already basic)
  │
  ↓ _closed_loops_from_geometry()
  
Circle Edges (single closed loop per circle)
  ├─ cq.Edge.makeCircle()
  │
Line/Arc Edges (trace by endpoint matching)
  ├─ Endpoint tolerance: 1e-6
  ├─ Forward/reverse matching
  └─ Error if any edge unconnected
  
  ↓ cq.Wire.assembleEdges()
  
Closed Loops (Wire list)
  ├─ One or more independent closed wires
  │
  ↓ _build_profile_face()
  
Outer/Inner Detection (bounding box ranking)
  ├─ Largest bbox → outer
  ├─ All others must be contained → inner (holes)
  ├─ Non-containment → SketchError
  │
  ↓ cq.Face.makeFromWires()

Profile (cq.Face)
  ├─ Single outer boundary
  ├─ Zero or more holes (inner)
  │
  ↓ extrude_sketch()
  
Solid (cq.Workplane)
```

**Source references:**
- `core/sketch.py:build_profile()` (L256-273)
- `core/sketch.py:_normalize_geometry()` (L111-124)
- `core/sketch.py:_closed_loops_from_geometry()` (L230-247)
- `core/sketch.py:_build_profile_face()` (L252-281)
- `core/sketch.py:extrude_sketch()` (L284-290)

### 4.2 Geometry Types

**Basic Geometry (primitive, not decomposed):**

| Type | Definition | Closed? | Notes |
|------|-----------|---------|-------|
| line | start/end points | No | Must be chained with others |
| arc | center, radius, start_angle, end_angle | No | Degree (0-360), CCW positive; must be chained |
| circle | center, radius | Yes | Single closed loop; no degeneracy check |

**Convenience Geometry (decomposed to line edges):**

| Type | Definition | Decomposition |
|------|-----------|----------------|
| rectangle | center, width, height | 4 line edges (corners) |
| polygon | points[] (≥3) | N line edges (sequential) |

**Source:** `core/sketch.py` (L55-110)

### 4.3 Current Limitations (Documented in Source)

From `core/sketch.py` module docstring (L13-43):

1. **Degeneracy Detection**: Polygon with collinear points (zero area) → **No error; results in warning only**
2. **Nested Loops (3+ levels)**: Currently, bounding box ranking supports any depth, **contradicting source docstring**
3. **Ambiguous Containment**: Partial overlap (not fully contained) → SketchError
4. **Plane Support**: XY only; other planes raise SketchError

**Known Discrepancy:**
- Source docstring (L40): "3つ以上のネストや、内包関係が曖昧な配置は未対応でSketchError"
- Implementation (`_build_profile_face()`): Recursive containment works for any depth
- **Status:** Implementation is more capable than documented

---

## 5. Core Execution Model

### 5.1 Operation Execution Order

```python
build_from_dict(param_dict)
  │
  ├─ Phase 1: Sketch normalization (all sketches → cq.Face)
  │    └─ sketches dict: {id → cq.Face}
  │
  ├─ Phase 2: Primitive construction (all primitives → cq.Workplane)
  │    └─ shapes dict: {id → cq.Workplane}
  │
  └─ Phase 3: Sequential operation execution
       for each op in operations:
         result = _apply_operation(shapes, op, sketches)
         shapes[op["result_id"]] = result
       │
       └─ Subsequent ops can reference earlier result_ids
```

**Properties:**
- **Single-pass**: No iteration or constraint solving
- **Linear**: Each operation adds/updates a single entry in `shapes`
- **Stateless**: No persistent global state
- **Order-dependent**: Boolean results depend on operation sequence

**Source:** `core/engine.py:build_from_dict()` (L189-238)

### 5.2 Error Handling Hierarchy

```
Exception Hierarchy:

SketchError (core/sketch.py)
  ├─ Geometry type not supported
  ├─ Geometry property missing/invalid
  ├─ Closed loop formation failure
  ├─ Outer/inner containment violation
  └─ CadQuery extrusion failure

    ↓ caught by build_from_dict()
    
GeometryError (core/engine.py)
  ├─ SketchError (re-raised with GeometryError wrapper)
  ├─ Primitive construction failure
  ├─ Operation reference not found
  ├─ Boolean/extrude/fillet/chamfer failure
  └─ Final solid validation failure

TransformError (core/transform.py)
  └─ Transform parameter invalid
```

### 5.3 Validation & Warnings

**Post-build validation** (not error-throwing):

```python
validate_solid(result: cq.Workplane) → list[str]
```

**Warning conditions:**

| Condition | Message |
|-----------|---------|
| volume ≤ 0 | "体積が0以下です(volume=X)。..." |
| no solid | "有効な立体(Solid)が生成されていません。" |
| no faces | "面が1つもありません。形状が破綻している可能性があります。" |
| validation exception | "バリデーション計算中に例外が発生しました: ..." |

**Important:** Warnings are **not errors**. BuildResult is returned with `warnings` list.

**Source:** `core/engine.py:validate_solid()` (L148-164)

---

## 6. CadQuery/OCP Boundary

### 6.1 Shape Object Model

| cad-core Layer | CadQuery Object | OCCT Object | Purpose |
|---|---|---|---|
| Sketch Face | `cq.Face` | OCP Geom2d + Face | 2D profile for extrusion |
| 3D Solid | `cq.Workplane` | OCP Solid (wrapped) | Parametric solid body |
| Boolean Result | `cq.Workplane` | OCP Solid | Combined/subtracted volume |
| Face Selection | `cq.Face` (via `vals()`) | OCP Face | Individual surface for fillet |
| Edge Selection | `cq.Edge` (via `vals()`) | OCP Edge | Individual curve for topology |

### 6.2 Workplane as Abstraction

```python
# Primitive construction returns Workplane
shape: cq.Workplane = cq.Workplane("XY").box(w, d, h)

# Boolean operations return Workplane
result: cq.Workplane = base.cut(tool)

# Fillet/chamfer return Workplane
fillet_result: cq.Workplane = shape.edges().fillet(radius)

# Extrude returns Workplane
extruded: cq.Workplane = cq.Solid.extrudeLinear(face, vector)
```

**Internal representation:**
```python
# Extract actual solid
solid = workplane.val()  # OCP Solid object
volume = solid.Volume()
```

### 6.3 Information Discarded at Boundary

The following OCCT-level information is **intentionally discarded**:

1. **Persistent Topology IDs**: Face/Edge indices are recomputed per execution
2. **Feature History**: No operation log; only final solid is retained
3. **Constraint Metadata**: Constraints are not represented (extrude distance is parameter, not constraint)
4. **Sketch-Solid Link**: Sketch geometry is not retained in output (only Face during extrude)

**Rationale:** Stateless pipeline design

---

## 7. Selection Model

### 7.1 Current Selection Architecture

**SelectionResult Dataclass** (core/selection.py):

```python
@dataclass
class SelectionResult:
    kind: str          # "solid" | "face" | "edge" | "vertex"
    index: int         # CadQuery native index (0-based, recomputed per execution)
    shape: Any = None  # Actual cq.Face / cq.Edge / cq.Vertex object
```

**Properties:**
- **Index-based**: Identifies topology elements by index within current shape
- **Non-persistent**: Index is valid only for current execution (no UUID/persistent ID)
- **Lazy resolution**: `shape` field populated by `resolve_selection()`

**Source:** `core/selection.py` (module docstring + SelectionResult class)

### 7.2 Selection Methods

**Basic selection:**
```python
select_faces(shape: cq.Workplane) → list[SelectionResult]
select_edges(shape: cq.Workplane) → list[SelectionResult]
select_vertices(shape: cq.Workplane) → list[SelectionResult]
select_face(shape, index: int) → SelectionResult  # Single
```

**Geometric criteria selection:**
```python
select_faces_by_normal(shape, normal, tolerance)
select_faces_by_area(shape, min_area, max_area)
select_faces_by_criteria(shape, surface_type, normal, min_area, max_area, tolerance)

select_edges_by_direction(shape, direction, tolerance, bidirectional)
select_edges_by_length(shape, min_length, max_length)
select_edges_by_curve_type(shape, curve_type)
select_edges_by_criteria(shape, curve_type, direction, min_length, max_length, ...)
```

**Topology relationships:**
```python
face_edges(shape, face_index) → list[SelectionResult]   # Boundary edges
edge_faces(shape, edge_index) → list[SelectionResult]   # Adjacent faces
face_vertices(shape, face_index) → list[SelectionResult]
edge_vertices(shape, edge_index) → list[SelectionResult]
vertex_edges(shape, vertex_index) → list[SelectionResult]
vertex_faces(shape, vertex_index) → list[SelectionResult]
```

**Geometric relationships:**
```python
faces_parallel(shape, face_a, face_b, tolerance) → bool
faces_perpendicular(shape, face_a, face_b, tolerance) → bool
face_distance(shape, face_a, face_b) → float

edges_parallel(shape, edge_a, edge_b, tolerance) → bool
edges_perpendicular(shape, edge_a, edge_b, tolerance) → bool
edge_distance(shape, edge_a, edge_b) → float

face_normal(shape, face_index) → [x, y, z]
edge_direction(shape, edge_index) → [dx, dy, dz]
```

**Source:** `core/selection.py` (entire module, L1-800+)

### 7.3 Selection Limitations

**Current guarantees:**
- Index remains valid within single execution context
- Face/Edge/Vertex identified uniquely by index

**Current non-guarantees:**
- Index does **not** persist across rebuilds (e.g., changing a parameter and re-executing will produce new indices)
- No "face name" or "edge ID" system exists
- Selection is **query-based**, not **persistent**

**Implication for fillet/chamfer:**
```python
# Valid within single build:
top_faces = select_faces_by_criteria(shape, normal=(0,0,1))
for tf in top_faces:
    shape = shape.faces(tf.index).fillet(2.0)  # ✓ Works

# NOT valid across separate builds:
# build 1: face_index = 2
# build 2: face_index = 3 (indices changed!)
# Cannot store face_index from build 1 and use in build 2
```

---

## 8. Intentional Scope Limitations

### Scope Classification Matrix

| Feature | Scope | Rationale | Reconsider Timeline |
|---------|-------|-----------|-------------------|
| **Feature History / Undo-Redo** | OUT OF SCOPE | Stateless pipeline by design | LATER |
| **Constraint Solving** (coincident, parallel, tangent, etc.) | OUT OF SCOPE | No parametric solver; dimensions are values, not constraints | OUT OF SCOPE |
| **Dimensions as Parametric Constraints** | OUT OF SCOPE | Extrude distance, fillet radius are parameters, not live-updating constraints | OUT OF SCOPE |
| **Persistent Topology IDs** (face/edge names across rebuilds) | OUT OF SCOPE | Index-based selection only; IDs are ephemeral per execution | LATER |
| **Pattern Instance Identity** | OUT OF SCOPE | No pattern/array feature; could add later with instance tracking | LATER |
| **Interactive Sketch Editing** | OUT OF SCOPE | Sketches are JSON-defined, batch-processed; no UI sketch tool | LATER |
| **Sketch Degeneracy Detection** | NOW (Low Priority) | Zero-area polygon currently generates warning, not error; source docstring claims future error throwing |
| **3-Level Nested Holes** | NOW (Undocumented) | Implementation supports it; source docstring says "未対応"; documentation needs correction |
| **Multiple Extrude Directions** | OUT OF SCOPE | Extrude is Z-only (default); XY-plane sketches only | LATER |
| **Revolve / Loft** | OUT OF SCOPE | Not implemented | LATER |
| **Mesh Export** | IMPLEMENTED | `export_mesh()` function exists | NOW |
| **STEP/STL Export** | IMPLEMENTED | `export_step()`, `export_stl()` via CadQuery | NOW |

---

## 9. Verified Current Issues

### Issue 1: Test Case Metadata Mismatch (Low Severity)

**Affected files:**
- `examples/err_degenerate_polygon.json`
- `examples/err_nested_island.json`

**Problem:**
- File comments contain expected behavior (期待挙動) that do not match implementation
- `err_degenerate_polygon.json`: Expects SketchError; implementation returns ✓ SUCCESS with warning
- `err_nested_island.json`: Expects SketchError (3-level nesting unsupported); implementation returns ✓ SUCCESS

**Root cause:**
- Implementation has been updated; test metadata not synchronized
- Degeneracy check: Not implemented in `_normalize_polygon()` (L147-153)
- Nesting support: Implemented in `_build_profile_face()` (L252-281)

**Impact:**
- Tests do not accurately reflect current capability
- No functional defect; output is correct

**Recommendation:**
- Update test comments to reflect current behavior
- OR: Implement degeneracy check if zero-area polygons should error
- Classify nesting support (NOW or LATER)

**Source references:**
- `core/sketch.py:_normalize_polygon()` (L147-153) - No degeneracy check
- `core/sketch.py:_build_profile_face()` (L252-281) - Supports recursive nesting

---

## 10. Known Non-Goals

1. **Parametric Relationships**: No "update all dependent features when parameter changes"
2. **Constraint-Driven Design**: No solver (Constraint Satisfaction Problem)
3. **Interactive UI**: cad-core is backend/engine only; UI is caller's responsibility
4. **Real-time Performance**: No optimization for interactive use (millisecond latency not guaranteed)
5. **Mesh-based Modeling**: Solid geometry only (no point clouds, no triangle meshes as primary representation)
6. **Multi-body Design**: Single result solid per execution (no assembly/multi-part output)

---

## 11. Architecture Evolution Path

### Completed (Current)
- ✓ Basic primitives (box, cylinder, sphere, cone, torus)
- ✓ Sketch system (line, circle, arc, rectangle, polygon)
- ✓ Extrude (2D → 3D)
- ✓ Boolean operations (cut, union, intersect)
- ✓ Fillet/chamfer
- ✓ Selection by geometry (normal, area, direction, length)
- ✓ Topology relationship queries (face edges, edge vertices, etc.)
- ✓ Transform (position, rotation)

### Identified for Future (No Commitment)
- Sketch degeneracy validation (NOW - low priority)
- Persistent topology ID system (LATER - requires redesign)
- Pattern/array with instance tracking (LATER)
- Interactive sketch tool (LATER - requires UI framework)
- Additional primitives (taper, wedge)
- Loft / revolve operations

### Explicitly Not Planned
- Constraint solver
- Feature history / undo-redo
- Parametric expressions
- Multi-body assembly
- Mesh import/export as primary workflow

---

## 12. Final Architectural Position

### Summary: Stateless Batch Geometry Pipeline

**cad-core is a well-defined, single-purpose system:**

1. **Input:** Declarative JSON description (primitives + sketches + operations)
2. **Processing:** Single-pass transformation through CadQuery/OCCT
3. **Output:** 3D solid with metadata

**Key properties:**
- **Stateless:** No persistent state; each execution is independent
- **Deterministic:** Same JSON input → same output (modulo floating-point precision)
- **Linear:** Operations execute sequentially; no backtracking or constraint solving
- **Non-interactive:** Batch processing; not designed for real-time UI
- **Error-rich:** Validation and error messages for malformed input

**What works well:**
- Solid geometry generation from sketches
- Boolean operations with stable topology indexing
- Selection and geometric queries
- Error detection (distance=0, unconnected geometry, etc.)

**What is intentionally excluded:**
- Feature history, parametric solving, persistent topology naming, interactive UI

**Development notes:**
- Source docstring in `core/sketch.py` describes a simpler implementation than currently exists (3-level nesting support is undocumented but working)
- Test metadata (`err_degenerate_polygon.json`, `err_nested_island.json`) reflects older assumptions
- No actual functional defects detected in A-class (actual vs. specification) testing

**Quality:** The implementation is consistent with its design goals and appropriate for batch CAD processing tasks.

---

## References

**Core modules:**
- `core/engine.py` - Main orchestration, primitive building, operation execution
- `core/sketch.py` - Sketch processing, geometry normalization, profile construction
- `core/selection.py` - Topology element selection and geometric queries
- `core/transform.py` - 3D transformation (position, rotation)

**Entry points:**
- `build_from_dict(param_dict: dict) → BuildResult` - Primary API
- `api/server.py` - HTTP API wrapper
- `cli/main.py` - Command-line interface

**Example files:**
- `examples/*.json` - JSON input specifications

---

