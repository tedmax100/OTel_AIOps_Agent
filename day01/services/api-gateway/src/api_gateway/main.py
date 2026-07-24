"""API gateway.

Routes /api/* paths to the appropriate backend. Thin proxy: we keep this
deliberately dumb so the agent can observe how upstream errors propagate
back up the call chain. httpx is auto-instrumented, so traceparent is
forwarded on every outgoing call.
"""

from __future__ import annotations

import json
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
from opentelemetry import trace

USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service.demo.svc:8000")
ORDER_SERVICE_URL = os.environ.get("ORDER_SERVICE_URL", "http://order-service.demo.svc:8000")
PAYMENT_SERVICE_URL = os.environ.get("PAYMENT_SERVICE_URL", "http://payment-service.demo.svc:8000")

setup_stdout_json_logging(level=os.environ.get("LOG_LEVEL", "INFO"))

_log = get_logger("api_gateway")
app = FastAPI(title="api-gateway")
_log.info("api-gateway started")

_client: httpx.AsyncClient | None = None


@app.on_event("startup")
async def _startup() -> None:
    global _client
    _client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _client is not None:
        await _client.aclose()


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


async def _proxy(method: str, url: str, request: Request) -> Any:
    assert _client is not None
    body = await request.body()
    try:
        resp = await _client.request(
            method,
            url,
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
            f"upstream unreachable: {url} ({exc.__class__.__name__})",
            upstream=url,
            reason="network",
        )
        raise HTTPException(status_code=502, detail="upstream unreachable") from exc

    if resp.status_code >= 500:
        log_event(
            _log,
            BizEvent.REQUEST_FAILED,
            f"upstream {url} returned {resp.status_code}",
            upstream=url,
            status=resp.status_code,
        )
    try:
        return resp.json() if resp.content else {}
    except ValueError:
        return {"raw": resp.text}


# ---- Routing table ----------------------------------------------------------


@app.get("/api/users")
async def users_list(request: Request):
    log_event(_log, BizEvent.REQUEST_RECEIVED, "GET /api/users", path="/api/users")
    return await _proxy("GET", f"{USER_SERVICE_URL}/api/users", request)


@app.get("/api/users/{user_id}")
async def users_get(user_id: str, request: Request):
    log_event(
        _log,
        BizEvent.REQUEST_RECEIVED,
        f"GET /api/users/{user_id}",
        path="/api/users/{id}",
    )
    return await _proxy("GET", f"{USER_SERVICE_URL}/api/users/{user_id}", request)


@app.get("/api/products")
async def products_list(request: Request):
    log_event(_log, BizEvent.REQUEST_RECEIVED, "GET /api/products", path="/api/products")
    return await _proxy("GET", f"{ORDER_SERVICE_URL}/api/products", request)


@app.get("/api/cart")
async def cart(request: Request):
    log_event(_log, BizEvent.REQUEST_RECEIVED, "GET /api/cart", path="/api/cart")
    return await _proxy("GET", f"{ORDER_SERVICE_URL}/api/cart", request)


@app.post("/api/orders")
async def orders_create(request: Request):
    # api-gateway is a thin proxy: it never parses the body into
    # order-service's model, so it never goes through the `userId`→`user_id`
    # alias order-service applies (see order_service.main.CreateOrderRequest).
    # Tagging whatever key the caller actually sent — un-normalized — is
    # exactly how a naming drift like this shows up in telemetry: the same
    # concept, spelled two different ways, depending on which service's logs
    # or spans you're looking at.
    body = await request.body()
    user_id_attrs: dict[str, str] = {}
    try:
        parsed = json.loads(body) if body else {}
    except ValueError:
        parsed = {}
    if isinstance(parsed.get("userId"), str):
        user_id_attrs["userId"] = parsed["userId"]
    elif isinstance(parsed.get("user_id"), str):
        user_id_attrs["user_id"] = parsed["user_id"]

    span = trace.get_current_span()
    for key, value in user_id_attrs.items():
        span.set_attribute(key, value)

    log_event(
        _log,
        BizEvent.REQUEST_RECEIVED,
        "POST /api/orders",
        path="/api/orders",
        **user_id_attrs,
    )
    return await _proxy("POST", f"{ORDER_SERVICE_URL}/api/orders", request)


@app.post("/api/payments")
async def payments_charge(request: Request):
    log_event(_log, BizEvent.REQUEST_RECEIVED, "POST /api/payments", path="/api/payments")
    return await _proxy("POST", f"{PAYMENT_SERVICE_URL}/charge", request)
