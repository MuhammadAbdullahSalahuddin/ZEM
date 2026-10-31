from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from zem.api.data_source import (
    get_decision_by_id,
    get_decisions,
    get_latest_seq,
    get_new_decisions,
)
from zem.contracts.models import AuditEvent

app = FastAPI(
    title="ZEM API",
    description="Read-only Zero-trust Enforcement API for MCP gateway telemetry",
    version="0.1.0",
)

# CORS configuration allowing local dev dashboards (both port 5173 and port 3000)
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Health check endpoint confirming API service readiness."""
    return {"status": "ok"}


@app.get("/api/decisions", response_model=list[AuditEvent])
def list_decisions(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AuditEvent]:
    """Retrieve recent gateway decisions, newest first.

    Delegates to data_source.get_decisions without direct file or db coupling.
    """
    return get_decisions(limit=limit)


@app.get("/api/decisions/{call_id}", response_model=AuditEvent)
def get_decision(call_id: str) -> AuditEvent:
    """Retrieve details for a single decision by its call_id.

    Returns 404 if the call_id was not found.
    """
    decision = get_decision_by_id(call_id)
    if decision is None:
        raise HTTPException(
            status_code=404,
            detail=f"Decision with call_id '{call_id}' not found",
        )
    return decision


@app.get("/api/stream")
async def stream_decisions(
    request: Request,
    after_seq: Annotated[int | None, Query(description="Stream events after this seq")] = None,
    limit: Annotated[
        int | None, Query(description="Maximum number of events to stream (for testing or batching)")
    ] = None,
) -> EventSourceResponse:
    """Stream live gateway audit decisions via Server-Sent Events (SSE).

    If after_seq is omitted, checks the Last-Event-ID header or defaults
    to the current latest sequence number.
    """

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        if after_seq is not None:
            current_seq = after_seq
        else:
            last_id = request.headers.get("last-event-id")
            if last_id and last_id.isdigit():
                current_seq = int(last_id)
            else:
                current_seq = get_latest_seq()

        # Send an immediate connection confirmation event to flush SSE headers
        yield {
            "event": "connected",
            "data": json.dumps({"connected": True, "seq": current_seq}),
        }

        events_sent = 0
        if limit is not None and limit <= 0:
            return

        while True:
            if await request.is_disconnected():
                break

            new_events = get_new_decisions(after_seq=current_seq)
            for ev in new_events:
                current_seq = max(current_seq, ev.seq)
                yield {
                    "event": "decision",
                    "id": str(ev.seq),
                    "data": ev.model_dump_json(),
                }
                events_sent += 1
                if limit is not None and events_sent >= limit:
                    return

            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator(), ping=15)
_WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"
if _WEB_DIST.is_dir():  # only when the dashboard has been built
    app.mount("/", StaticFiles(directory=_WEB_DIST, html=True), name="web")
