"""
api/server.py
──────────────────────────────────────────────────────────────────────
flow-mind / quick-ref との境界層。

【設計思想】
このファイルがエコシステム全体の"疎結合の切断面"。
- 受け取るのは自然言語ではなく、既に構造化されたパラメータ辞書(JSON)のみ
- 自然言語解析・音声認識・意図解釈は一切ここでは行わない
  （それはflow-mind/quick-ref側の責務。CADコア側では二重実装しない）
- 返すのは「幾何計算の結果」（体積・メッシュ・STEP等）のみ

起動方法:
  pip install fastapi uvicorn cadquery
  uvicorn api.server:app --reload --port 8420
"""

from __future__ import annotations
import os
import uuid
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core.engine import (
    build_from_dict,
    check_interference,
    export_mesh,
    export_step,
    export_stl,
    GeometryError,
)

app = FastAPI(title="CAD Core Engine", version="0.2.0")

CAD_TOKEN = os.environ.get("CAD_ENGINE_TOKEN", "")
OUTPUT_DIR = os.environ.get("CAD_OUTPUT_DIR", "./output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


class Primitive(BaseModel):
    id: str
    type: str
    params: dict = Field(default_factory=dict)


class Operation(BaseModel):
    op: str
    base: str | None = None
    tool: str | None = None
    target: str | None = None
    radius: float | None = None
    result_id: str | None = None


class BuildRequest(BaseModel):
    units: str = "mm"
    primitives: list[Primitive]
    operations: list[Operation] = Field(default_factory=list)


# --- TASK 3 用: 干渉チェックリクエストスキーマ ---
class InterferenceRequest(BaseModel):
    units: str = "mm"
    part_a: BuildRequest
    part_b: BuildRequest


def _check_token(x_cad_token: str | None):
    if not CAD_TOKEN:
        return
    if x_cad_token != CAD_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")


@app.post("/api/build")
def build(req: BuildRequest, x_cad_token: str | None = Header(default=None)):
    _check_token(x_cad_token)
    try:
        result = build_from_dict(req.model_dump())
    except GeometryError as e:
        raise HTTPException(status_code=422, detail=str(e))

    mesh = export_mesh(result.solid)

    return {
        "volume": result.volume,
        "face_count": result.face_count,
        "edge_count": result.edge_count,
        "warnings": result.warnings,
        "mesh": mesh,
    }


@app.post("/api/build/export")
def build_and_export(req: BuildRequest, fmt: str = "step", x_cad_token: str | None = Header(default=None)):
    _check_token(x_cad_token)
    if fmt not in ("step", "stl"):
        raise HTTPException(status_code=400, detail="fmt must be 'step' or 'stl'")

    try:
        result = build_from_dict(req.model_dump())
    except GeometryError as e:
        raise HTTPException(status_code=422, detail=str(e))

    filename = f"{uuid.uuid4().hex}.{fmt}"
    filepath = os.path.join(OUTPUT_DIR, filename)

    if fmt == "step":
        export_step(result.solid, filepath)
    else:
        export_stl(result.solid, filepath)

    return FileResponse(filepath, filename=filename)


# --- TASK 3: 干渉チェックAPIエンドポイント ---
@app.post("/api/interference")
def interference(req: InterferenceRequest, x_cad_token: str | None = Header(default=None)):
    """
    2つの部品パラメータ(part_a, part_b)を受け取り、3D空間上での重なり（干渉）を判定する。
    """
    _check_token(x_cad_token)
    try:
        shape_a = build_from_dict(req.part_a.model_dump()).solid
        shape_b = build_from_dict(req.part_b.model_dump()).solid
        res = check_interference(shape_a, shape_b)
        return res
    except GeometryError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/api/health")
def health():
    return {"status": "ok", "engine": "cadquery/OCCT"}