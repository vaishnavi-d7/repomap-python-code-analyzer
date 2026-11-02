"""FastAPI wrapper for RepoMap's local-directory analyzer."""

from __future__ import annotations

from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from analyzer import analyze_repository

app = FastAPI(
    title="RepoMap API",
    description="Analyze a local Python repository and return its code graph as JSON.",
    version="0.1.0",
)


class AnalyzeRequest(BaseModel):
    path: str = Field(
        min_length=1,
        description="Path to a repository directory on the machine running this API.",
        examples=["./example-repo"],
    )


_latest_graph: dict[str, Any] | None = None
_graph_lock = Lock()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze")
def analyze(request: AnalyzeRequest) -> dict[str, Any]:
    global _latest_graph
    try:
        graph = analyze_repository(request.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with _graph_lock:
        _latest_graph = graph
    return graph


@app.get("/graph")
def get_graph() -> dict[str, Any]:
    with _graph_lock:
        if _latest_graph is None:
            raise HTTPException(
                status_code=404,
                detail="No graph yet. POST a repository path to /analyze first.",
            )
        return _latest_graph
