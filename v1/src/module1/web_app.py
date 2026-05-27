# 这个文件提供模块一前端工作台的 FastAPI 服务，负责对话入口、SSE 事件流和结果读取。
from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from module1.models import EventInfoPackage
from module1.settings import load_module1_settings
from module1.traced_runner import run_module1_traced


V1_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = V1_ROOT / "web"


class RunRequest(BaseModel):
    """前端发起一次 Agent 采集运行时提交的参数。"""

    message: str


@dataclass
class RunState:
    """服务端保存的一次运行状态。"""

    run_id: str
    event_query: str
    events: list[dict] = field(default_factory=list)
    event_queue: "queue.Queue[dict | None]" = field(default_factory=queue.Queue)
    status: str = "running"
    package: EventInfoPackage | None = None
    output_dir: Path | None = None
    error: str | None = None
    trace_dir: Path | None = None


app = FastAPI(title="Module 1 Agent Workbench")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
RUNS: dict[str, RunState] = {}


@app.get("/")
def index() -> FileResponse:
    """返回前端工作台首页。"""

    return FileResponse(WEB_DIR / "index.html")


@app.post("/api/runs")
def start_run(request: RunRequest) -> dict:
    """创建一次新的模块一采集任务，并启动后台线程。"""

    event_query = request.message.strip()
    if not event_query:
        raise HTTPException(status_code=400, detail="message is required")

    run_id = f"run_{uuid4().hex[:12]}"
    state = RunState(
        run_id=run_id,
        event_query=event_query,
        trace_dir=V1_ROOT / "data" / "module1" / "runs" / run_id,
    )
    RUNS[run_id] = state
    _append_event(state, "chat", "user", event_query, {"run_id": run_id})

    thread = threading.Thread(target=_run_worker, args=(state,), daemon=True)
    thread.start()
    return {"run_id": run_id, "status": state.status}


@app.get("/api/runs")
def list_runs() -> dict:
    """列出当前后端进程内还保留的运行记录，方便调试最近一次执行。"""

    return {
        "runs": [
            _state_payload(state)
            for state in sorted(RUNS.values(), key=lambda item: item.events[-1]["created_at"] if item.events else "")
        ]
    }


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    """读取一次运行的当前状态和已有事件。"""

    state = _get_state(run_id)
    return _state_payload(state)


@app.get("/api/runs/{run_id}/events")
def stream_events(run_id: str) -> StreamingResponse:
    """用 Server-Sent Events 持续推送 agent 中间过程。"""

    state = _get_state(run_id)

    def generator():
        if state.status != "running":
            for event in state.events:
                yield _sse(event)
            yield _sse({"type": "stream", "status": state.status, "message": "stream closed", "data": None})
            return
        while state.status == "running":
            try:
                item = state.event_queue.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            if item is None:
                break
            yield _sse(item)
        yield _sse({"type": "stream", "status": state.status, "message": "stream closed", "data": None})

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.get("/api/runs/{run_id}/package")
def get_package(run_id: str) -> JSONResponse:
    """读取最终事件基础信息库 JSON。"""

    state = _get_state(run_id)
    if state.package is None:
        raise HTTPException(status_code=404, detail="package is not ready")
    return JSONResponse(state.package.model_dump(mode="json"))


@app.get("/api/runs/{run_id}/sources/{source_id}")
def get_source_text(run_id: str, source_id: str) -> PlainTextResponse:
    """读取某个来源正文 txt，供前端预览。"""

    state = _get_state(run_id)
    if state.package is None:
        raise HTTPException(status_code=404, detail="package is not ready")
    document = next((item for item in state.package.source_documents if item.source_id == source_id), None)
    if document is None or not document.raw_text_path:
        raise HTTPException(status_code=404, detail="source text is not available")
    path = Path(document.raw_text_path)
    if not path.is_absolute():
        path = V1_ROOT / path
    if not path.exists():
        raise HTTPException(status_code=404, detail="source text file is missing")
    return PlainTextResponse(path.read_text(encoding="utf-8", errors="replace"))


def _run_worker(state: RunState) -> None:
    """后台运行模块一，并把每一步发到事件队列。"""

    def emit(step: str, status: str, message: str, data: dict | None) -> None:
        _append_event(state, step, status, message, data)

    try:
        emit("chat", "assistant", "收到事件输入，开始启动模块一采集。", None)
        settings = load_module1_settings()
        package, output_dir = run_module1_traced(state.event_query, settings=settings, emit=emit)
        state.package = package
        state.output_dir = output_dir
        state.status = "completed"
        emit(
            "chat",
            "assistant",
            "采集完成，事件基础信息库已经写入本地。",
            {
                "event_id": package.event_id,
                "output_dir": str(output_dir),
                "source_documents": len(package.source_documents),
                "news_blocks": len(package.news_blocks),
            },
        )
        _persist_trace(state)
    except Exception as exc:
        state.status = "failed"
        state.error = str(exc)
        emit("error", "failed", "运行失败", {"error": state.error})
        _persist_trace(state)
    finally:
        state.event_queue.put(None)


def _append_event(state: RunState, event_type: str, status: str, message: str, data: dict | None) -> None:
    event = {
        "id": len(state.events) + 1,
        "run_id": state.run_id,
        "type": event_type,
        "status": status,
        "message": message,
        "data": data,
        "created_at": datetime.now(UTC).isoformat(),
    }
    state.events.append(event)
    state.event_queue.put(event)
    _persist_trace(state)


def _state_payload(state: RunState) -> dict:
    return {
        "run_id": state.run_id,
        "event_query": state.event_query,
        "status": state.status,
        "error": state.error,
        "output_dir": str(state.output_dir) if state.output_dir else None,
        "trace_dir": str(state.trace_dir) if state.trace_dir else None,
        "event_count": len(state.events),
        "package": state.package.model_dump(mode="json") if state.package else None,
    }


def _get_state(run_id: str) -> RunState:
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="run not found")
    return state


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _persist_trace(state: RunState) -> None:
    """把运行 trace 持续写入磁盘，方便失败后回看每一步 agent 行为。"""

    if state.trace_dir is None:
        return
    state.trace_dir.mkdir(parents=True, exist_ok=True)
    (state.trace_dir / "trace_events.json").write_text(
        json.dumps(state.events, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (state.trace_dir / "run_state.json").write_text(
        json.dumps(
            {
                "run_id": state.run_id,
                "event_query": state.event_query,
                "status": state.status,
                "error": state.error,
                "output_dir": str(state.output_dir) if state.output_dir else None,
                "event_count": len(state.events),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
