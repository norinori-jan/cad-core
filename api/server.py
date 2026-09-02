from __future__ import annotations
import os
import uuid
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core.engine import (
    build_from_dict, check_interference, export_mesh, export_step, export_stl, GeometryError,
)

app = FastAPI(title="CAD Core Engine", version="0.3.1")
CAD_TOKEN = os.environ.get("CAD_ENGINE_TOKEN", "")
OUTPUT_DIR = os.environ.get("CAD_OUTPUT_DIR", "./output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

class Primitive(BaseModel):
    id: str
    type: str
    params: dict = Field(default_factory=dict)

class Sketch(BaseModel):
    id: str
    plane: str = "XY"
    geometry: list[dict]

class Operation(BaseModel):
    op: str
    base: str | None = None
    tool: str | None = None
    target: str | None = None
    sketch: str | None = None
    distance: float | None = None
    radius: float | None = None
    edges: list[int] | None = None
    result_id: str | None = None

class BuildRequest(BaseModel):
    units: str = "mm"
    primitives: list[Primitive] = Field(default_factory=list)
    sketches: list[Sketch] = Field(default_factory=list)
    operations: list[Operation] = Field(default_factory=list)

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
    return {"volume": result.volume, "face_count": result.face_count, "edge_count": result.edge_count, "warnings": result.warnings, "mesh": mesh}

@app.get("/api/health")
def health():
    return {"status": "ok"}
