# cad-core Architecture

## 1. Product Boundary

### What cad-core IS

**cad-core is a stateless JSON → solid batch geometry pipeline.**

- Input: JSON definition (primitives, sketches, operations)
- Processing: Single-pass transformation through geometry engine
- Output: 3D solid (CadQuery Workplane) with metadata (volume, face count, edge count, warnings)
- Execution model: No persistent state between invocations
- API: `build_from_dict(param_dict: dict) → BuildResult`

**Source:** `core/engine.py:build_from_dict()`

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
  │         ├─ detect outer/inner (bounding box ranking) ← ⚠️ 2階層までしか正しく機能しない(§4.3参照)
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
  ├─ isValid() check (OCCT topology validity) ← 今回追加
  ├─ volume check (warn if ≤ 0)
  ├─ face/edge count
  └─ BuildResult(solid, volume, face_count, edge_count, warnings)
```

**Source references:**
- `core/engine.py:build_from_dict()` - Main orchestration
- `core/engine.py:_apply_operation()` - Operation execution
- `core/sketch.py:build_profile()` - Sketch→Face conversion
- `core/engine.py:validate_solid()` - Result validation (isValid()チェックを含む)

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
- **⚠️ 3階層以上のネストされた閉ループは、エラーにならず実行は完了するが、
  生成される形状は無効(isValid()=False)になる（§4.3参照。実際に検証済み）**

**Source:** `core/sketch.py:build_profile()`, `core/sketch.py:_closed_loops_from_geometry()`

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

**Source:** `core/engine.py:_build_primitive()`

### 3.3 Operations

**Operand Reference Model: String IDs**

All operands reference shapes by string ID (not array index, not object identity):

```json
{"op": "cut", "base": "box_a", "tool": "hole_cyl", "result_id": "result_1"}
```

- `"base"` / `"tool"`: String ID matching a primitive or previous operation result
- `"result_id"`: Required; labels this operation's output for reference by subsequent operations
- Reference resolution: Linear search in `shapes: dict[str, cq.Workplane]`

**Verification:** `core/engine.py:_apply_operation()` — 実際に実行して確認済み。配列インデックス参照
(`a: 0, b: 1`のような形式)は実装に一切存在しない。

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
| cut / subtract | base + tool | base.cut(tool)（subtractはcutのエイリアス） |
| union | base + tool | base.union(tool) |
| intersect | base + tool | base.intersect(tool) |
| fillet | target + radius | target.edges().fillet(radius) |
| chamfer | target + distance | target.edges().chamfer(distance) |

**Source:** `core/engine.py:_apply_operation()`

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
  
Outer/Inner Detection (bounding box ranking) ← ⚠️ フラットな判定。階層を区別しない(§4.3参照)
  ├─ Largest bbox → outer
  ├─ 残り全部を無条件でinner(穴)として扱う
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
- `core/sketch.py:build_profile()`
- `core/sketch.py:_normalize_geometry()`
- `core/sketch.py:_closed_loops_from_geometry()`
- `core/sketch.py:_build_profile_face()`
- `core/sketch.py:extrude_sketch()`

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

**Source:** `core/sketch.py`

### 4.3 Current Limitations (訂正版・実際に検証済み)

#### 縮退ポリゴン（面積0）

`_normalize_polygon()`に縮退チェックは無い。面積0のポリゴン（例：一直線上の3点）を渡すと、
`SketchError`にはならず、`build_from_dict()`は成功し、`volume=0.0`の警告のみが返る。
実行して確認済み。**軽微な仕様の食い違い（テストケースのコメントが古い）であり、
危険な誤動作ではない。**

#### ⚠️ 3階層以上のネスト（実際の欠陥・修正済み）

**旧版のこのドキュメントには「実装はdocstringより高機能で、任意の深さのネストに対応している」
と書かれていたが、これは誤りだった。実際に3階層のネスト（outer 100×100 → hole 60×60 →
island 20×20）を実行して検証した結果：**

- `SketchError`は発生せず、`build_from_dict()`は成功する
- しかし返される体積は`30000`（本来、島が実体として残るなら`34000`になるはず）
- 生成されたソリッドに対して`solid.isValid()`を呼ぶと**`False`が返る**
  （OCCT自身がこの形状をトポロジー的に無効と判定している）
- 原因：`_build_profile_face()`が`outer`以外の全ループを無条件で`inner`(穴)として扱っており、
  「穴の中の島」という階層構造を区別する仕組みが無いため

**つまり、元のdocstring（「3つ以上のネストは未対応でSketchError」）の方が正しい設計判断であり、
実装がそれより高機能だったわけではない。単に、無効な形状を生成してもエラーにならずに
成功として返してしまう、というバグだった。**

**対応済み：** `validate_solid()`に`isValid()`チェックを追加し、この状態を警告として検出できる
ようにした（`core/engine.py`、実行して確認済み。既存の正常系5パターンで誤検知しないことも
確認済み）。

```python
if hasattr(solid, "isValid") and not solid.isValid():
    warnings.append(
        "生成された形状はOCCTの妥当性検証(isValid)に失敗しています。"
        "複数の閉ループ(特に3階層以上のネスト)が正しく処理されていない可能性が高く、"
        "体積・面数・メッシュの値は信頼できません。"
    )
```

**未対応（次のタスク）：** `_build_profile_face()`自体で3階層以上を検出した時点で
`SketchError`にする根本修正。現状は「実行後に警告で気づける」段階に留まる。

#### 曖昧な内包関係

一部重なるが完全には内包されない配置は`SketchError`になる（実行して確認済み、想定通り）。

#### 平面対応

`XY`のみ。それ以外は`SketchError`（未検証だが実装上明らか）。

**Source:** `core/sketch.py`, `core/engine.py:validate_solid()`

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

**Source:** `core/engine.py:build_from_dict()`

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
| no solid | "有効な立体(Solid)が生成されていません。" |
| **isValid()=False（今回追加）** | **"生成された形状はOCCTの妥当性検証(isValid)に失敗しています。..."** |
| volume ≤ 0 | "体積が0以下です(volume=X)。..." |
| no faces | "面が1つもありません。形状が破綻している可能性があります。" |
| validation exception | "バリデーション計算中に例外が発生しました: ..." |

**Important:** Warnings are **not errors**. BuildResult is returned with `warnings` list.
呼び出し側は`warnings`を必ず確認すべきで、特に`isValid()`失敗の警告が出た場合は
結果の体積・メッシュを信頼してはいけない。

**Source:** `core/engine.py:validate_solid()`

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
is_valid = solid.isValid()  # 今回追加。呼ばないと壊れた形状を見逃す
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
@dataclass(frozen=True)
class SelectionResult:
    kind: str          # "solid" | "face" | "edge" | "vertex"
    index: int         # CadQuery native index (0-based, recomputed per execution)
    shape: Any = None  # Actual cq.Face / cq.Edge / cq.Vertex object
```

実際にアップロードされたファイルと突き合わせて、この定義が一致することを確認済み。

**Properties:**
- **Index-based**: Identifies topology elements by index within current shape
- **Non-persistent**: Index is valid only for current execution (no UUID/persistent ID)
- **Lazy resolution**: `shape` field populated by `resolve_selection()`

**Source:** `core/selection.py`（1638行、実際に構文チェック・importまで確認済み）

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

**Source:** `core/selection.py`（全体は今回まだ機能単位での実行検証はしていない。
`SelectionResult`の定義一致のみ確認済み）

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
| **Sketch Degeneracy Detection** | NOW (Low Priority) | Zero-area polygon currently generates warning, not error |
| **3-Level Nested Holes（訂正）** | **NOW（実欠陥として修正着手済み）** | **エラーにならず無効なソリッドを静かに返す。isValid()警告は追加済み。根本修正(SketchError化)は未実施** |
| **Multiple Extrude Directions** | OUT OF SCOPE | Extrude is Z-only (default); XY-plane sketches only | LATER |
| **Revolve / Loft** | OUT OF SCOPE | Not implemented | LATER |
| **Mesh Export** | IMPLEMENTED | `export_mesh()` function exists | NOW |
| **STEP/STL Export** | IMPLEMENTED | `export_step()`, `export_stl()` via CadQuery | NOW |

---

## 9. Verified Current Issues

### Issue 1: Test Case Metadata Mismatch (Low Severity・確認済み)

**Affected files:**
- `examples/err_degenerate_polygon.json`
- `examples/err_nested_island.json`

**Problem:**
- File comments contain expected behavior (期待挙動) that do not match implementation
- `err_degenerate_polygon.json`: Expects SketchError; implementation returns ✓ SUCCESS with warning
  （実行して再現済み。`volume=0.0`、警告あり）

**Root cause:**
- Degeneracy check: Not implemented in `_normalize_polygon()`

**Impact:** テストは現状の挙動を正確に反映していないが、機能的な欠陥ではない。

**Recommendation:** テストのコメントを現状の挙動に合わせて更新するか、縮退チェックを実装するか。

---

### Issue 2: 3階層以上のネストで無効なソリッドが生成される (実欠陥・修正済み)

**発見の経緯：** 旧版の本ドキュメントが「実装はdocstringより高機能で任意深さのネストに対応」と
主張していたため、実際にJSONを組み立てて実行し検証した。

**再現手順：**
```json
{
  "sketches":[{"id":"s3","plane":"XY","geometry":[
    {"type":"rectangle","center":[0,0],"width":100,"height":100},
    {"type":"rectangle","center":[0,0],"width":60,"height":60},
    {"type":"rectangle","center":[0,0],"width":20,"height":20}
  ]}],
  "operations":[{"op":"extrude","sketch":"s3","distance":5,"result_id":"final"}]
}
```

**結果：**
- `build_from_dict()`は例外を投げず成功する
- `volume = 30000.0`（本来、島が実体として残るなら34000になるはず。差の4000は
  「本来は実体であるべき内側の20×20×5の島」の体積と一致する）
- `result_shape.val().isValid()` → `False`
- `len(result_shape.solids().vals())` → `1`（分離した複数ソリッドにはなっていない、
  単一の無効なソリッドとして統合されている）

**根本原因：** `_build_profile_face()`が、`outer`以外の全ての閉ループを無条件で`inner`(穴)として
扱っており、「穴の中の島」という階層を区別していない。

**対応：** `validate_solid()`に`isValid()`チェックを追加し、この状態を警告として検出できるように
した。既存の正常系5パターン（box, torus, basic example, 穴あきprofile, Sketch+extrude+subtract）
で誤検知しないことも確認済み。

**未対応：** `_build_profile_face()`自体で3階層以上を`SketchError`にする根本修正。

**Source references:**
- `core/sketch.py:_build_profile_face()`
- `core/engine.py:validate_solid()`（修正箇所）

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
- ✓ isValid()による形状妥当性チェック（今回追加）

### Identified for Future (No Commitment)
- Sketch degeneracy validation (NOW - low priority)
- **3階層以上ネストのSketchError化（NOW - 根本修正、isValid警告は対症療法に留まる）**
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

**What works well（実行して確認済み）:**
- Solid geometry generation from sketches（line/arc連結、穴あきprofile含む）
- Boolean operations with stable string-ID-based referencing
- Selection module構造（SelectionResultの定義）
- Error detection（座標不足、閉じないループ等）
- **形状の妥当性検証（isValid()、今回追加）**

**What is intentionally excluded:**
- Feature history, parametric solving, persistent topology naming, interactive UI

**What was found broken and fixed in this session:**
- 3階層以上のネストで無効なソリッドが警告無しに返っていた問題。isValid()チェックで検出可能に。

**Development notes:**
- Test metadata (`err_degenerate_polygon.json`) reflects older assumptions（軽微、実害なし）
- 3階層ネストの実欠陥は、このドキュメントの前バージョンの誤った楽観的評価
  （「監査より実装が優れている」）によって見過ごされていた。**「動く」ことと「正しく動く」ことは
  別であり、isValid()のような妥当性検証を伴わない検証は不十分**、という教訓として記録する。

**Quality:** The implementation is broadly consistent with its design goals, with one verified
correctness gap (3-level nesting) now detectable via warnings, and pending a root-cause fix.

---

## References

**Core modules:**
- `core/engine.py` - Main orchestration, primitive building, operation execution, validation（今回修正）
- `core/sketch.py` - Sketch processing, geometry normalization, profile construction
- `core/selection.py` - Topology element selection and geometric queries（1638行、定義一致のみ確認済み）
- `core/transform.py` - 3D transformation (position, rotation)

**Entry points:**
- `build_from_dict(param_dict: dict) → BuildResult` - Primary API
- `api/server.py` - HTTP API wrapper

**Example files:**
- `examples/*.json` - JSON input specifications

---

*Document generated from source code verification, then corrected after executing actual test
cases and discovering a real defect (3-level nesting → invalid solid) that the initial version
of this document had incorrectly characterized as a working feature.*

*Last updated: 2026-08-31（3階層ネスト欠陥の発見・isValid()修正を反映）*
