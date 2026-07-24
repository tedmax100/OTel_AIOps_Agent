"""Webapp — edge service.

Trace root for user-originated requests. Forwards /api/* to api-gateway
unchanged; the value here is being the public entrypoint so traces have a
consistent top-level service name.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from o11y_shared import (
    BizEvent,
    get_logger,
    log_event,
    setup_stdout_json_logging,
)

API_GATEWAY_URL = os.environ.get("API_GATEWAY_URL", "http://api-gateway.demo.svc:8000")

setup_stdout_json_logging(level=os.environ.get("LOG_LEVEL", "INFO"))

_log = get_logger("webapp")
app = FastAPI(title="webapp")
_log.info("webapp started")

_client: httpx.AsyncClient | None = None


@app.on_event("startup")
async def _startup() -> None:
    global _client
    _client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _client is not None:
        await _client.aclose()


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/")
async def root() -> dict:
    return {"service": "webapp", "ok": True}


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(path: str, request: Request) -> Any:
    assert _client is not None
    target = f"{API_GATEWAY_URL}/api/{path}"
    log_event(
        _log,
        BizEvent.REQUEST_RECEIVED,
        f"{request.method} /api/{path}",
        method=request.method,
        path=f"/api/{path}",
    )
    body = await request.body()
    try:
        resp = await _client.request(
            request.method,
            target,
            content=body or None,
            params=dict(request.query_params),
            headers={"content-type": request.headers.get("content-type", "application/json")}
            if body
            else None,
        )
    except httpx.HTTPError as exc:
        log_event(
            _log,
            BizEvent.REQUEST_FAILED,
            f"api-gateway unreachable: {exc.__class__.__name__}",
            upstream=target,
            reason="network",
        )
        raise HTTPException(status_code=502, detail="api-gateway unreachable") from exc

    if resp.status_code >= 500:
        log_event(
            _log,
            BizEvent.REQUEST_FAILED,
            f"api-gateway returned {resp.status_code} for /api/{path}",
            upstream=target,
            status=resp.status_code,
        )
    try:
        return resp.json() if resp.content else {}
    except ValueError:
        return {"raw": resp.text}
