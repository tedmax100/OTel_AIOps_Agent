"""Order service.

Owns products / cart / orders. POST /api/orders calls user-service for an
auth check and payment-service for the charge — those httpx calls inherit
the current trace context automatically (httpx auto-instrumentation).
"""

import os
import time
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from o11y_shared import (
    BizEvent,
    FeatureFlags,
    get_logger,
    log_event,
    setup_stdout_json_logging,
)
from opentelemetry import metrics
from pydantic import BaseModel, ConfigDict, Field

USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service.demo.svc:8000")
PAYMENT_SERVICE_URL = os.environ.get("PAYMENT_SERVICE_URL", "http://payment-service.demo.svc:8000")

setup_stdout_json_logging(level=os.environ.get("LOG_LEVEL", "INFO"))

_products = {
    f"p-{i}": {"id": f"p-{i}", "name": f"product-{i}", "price_cents": 100 * i} for i in range(1, 11)
}
_orders: dict[str, dict] = {}
_flags = FeatureFlags(file_path=os.environ.get("FEATURE_FLAGS_PATH"))
_log = get_logger("order_service")
_meter = metrics.get_meter("order_service")
_orders_counter = _meter.create_counter(
    "orders_total",
    description="Total order attempts",
)
_order_latency = _meter.create_histogram(
    "order_create_duration_seconds",
    description="Order creation handler duration",
    unit="s",
    # Recorded in SECONDS (perf_counter). Without this, the SDK's default
    # millisecond boundaries collapse every sub-second sample into the first
    # bucket and histogram_quantile returns a constant ~4.75 artifact. These
    # seconds-scaled boundaries give real resolution. See payment-service note.
    explicit_bucket_boundaries_advisory=[
        0.001,
        0.0025,
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
    ],
)

app = FastAPI(title="order-service")
_log.info("order-service started")

_client: httpx.AsyncClient | None = None


class CreateOrderRequest(BaseModel):
    # Some callers send the JS-convention `userId` instead of `user_id`. This
    # alias quietly accepts either spelling and normalizes to `req.user_id`
    # from here on — but nothing upstream of this model knows that happened,
    # so a service reading the raw JSON body (see api-gateway's /api/orders
    # handler) still sees whichever key the caller actually used.
    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(alias="userId")
    product_id: str
    quantity: int = Field(gt=0, default=1)


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


@app.get("/api/products")
async def list_products() -> dict:
    return {"products": list(_products.values())}


@app.get("/api/cart")
async def get_cart(user_id: str = "u-1") -> dict:
    return {"user_id": user_id, "items": []}


@app.post("/api/orders")
async def create_order(req: CreateOrderRequest) -> dict:
    assert _client is not None
    start = time.perf_counter()
    product = _products.get(req.product_id)
    if product is None:
        log_event(
            _log,
            BizEvent.ORDER_CANCELLED,
            f"unknown product {req.product_id}",
            user_id=req.user_id,
            product_id=req.product_id,
            reason="unknown_product",
        )
        _orders_counter.add(1, {"status": "cancelled", "reason": "unknown_product"})
        raise HTTPException(status_code=404, detail="product not found")

    try:
        auth = await _client.get(f"{USER_SERVICE_URL}/api/users/{req.user_id}/authcheck")
        auth.raise_for_status()
    except httpx.HTTPStatusError as exc:
        log_event(
            _log,
            BizEvent.ORDER_CANCELLED,
            f"auth failed for {req.user_id}: {exc.response.status_code}",
            user_id=req.user_id,
            reason="auth_failed",
            upstream_status=exc.response.status_code,
        )
        _orders_counter.add(1, {"status": "cancelled", "reason": "auth"})
        _order_latency.record(time.perf_counter() - start, {"status": "cancelled"})
        raise HTTPException(status_code=401, detail="auth failed") from exc
    except httpx.HTTPError as exc:
        log_event(
            _log,
            BizEvent.REQUEST_FAILED,
            f"user-service unreachable: {exc.__class__.__name__}",
            upstream="user-service",
            reason="network",
        )
        _orders_counter.add(1, {"status": "error", "reason": "user_upstream"})
        _order_latency.record(time.perf_counter() - start, {"status": "error"})
        raise HTTPException(status_code=502, detail="user-service unreachable") from exc

    amount_cents = product["price_cents"] * req.quantity
    try:
        pay = await _client.post(
            f"{PAYMENT_SERVICE_URL}/charge",
            json={
                "order_id": f"o-{uuid.uuid4().hex[:8]}",
                "user_id": req.user_id,
                "amount_cents": amount_cents,
            },
        )
        pay.raise_for_status()
    except httpx.HTTPStatusError as exc:
        log_event(
            _log,
            BizEvent.ORDER_CANCELLED,
            f"payment declined: {exc.response.status_code}",
            user_id=req.user_id,
            reason="payment_declined",
            upstream_status=exc.response.status_code,
        )
        _orders_counter.add(1, {"status": "cancelled", "reason": "payment"})
        _order_latency.record(time.perf_counter() - start, {"status": "cancelled"})
        raise HTTPException(status_code=402, detail="payment declined") from exc
    except httpx.HTTPError as exc:
        log_event(
            _log,
            BizEvent.REQUEST_FAILED,
            f"payment-service unreachable: {exc.__class__.__name__}",
            upstream="payment-service",
            reason="network",
        )
        _orders_counter.add(1, {"status": "error", "reason": "payment_upstream"})
        _order_latency.record(time.perf_counter() - start, {"status": "error"})
        raise HTTPException(status_code=502, detail="payment-service unreachable") from exc

    order_id = f"o-{uuid.uuid4().hex[:8]}"
    _orders[order_id] = {
        "id": order_id,
        "user_id": req.user_id,
        "product_id": req.product_id,
        "quantity": req.quantity,
        "amount_cents": amount_cents,
        "status": "created",
    }
    log_event(
        _log,
        BizEvent.ORDER_CREATED,
        f"order {order_id} created for user {req.user_id}",
        order_id=order_id,
        user_id=req.user_id,
        amount_cents=amount_cents,
    )
    _orders_counter.add(1, {"status": "created"})
    _order_latency.record(time.perf_counter() - start, {"status": "created"})
    return _orders[order_id]
