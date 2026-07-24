"""User service.

Owns user lookup + a synthetic auth-check endpoint used by order-service.
Zero-code OTel via `opentelemetry-instrument` in the container CMD.
"""

import os
import random

from fastapi import FastAPI, HTTPException
from o11y_shared import (
    BizEvent,
    FeatureFlags,
    get_logger,
    log_event,
    setup_stdout_json_logging,
)
from opentelemetry import metrics

setup_stdout_json_logging(level=os.environ.get("LOG_LEVEL", "INFO"))

_users: dict[str, dict] = {
    f"u-{i}": {"id": f"u-{i}", "name": f"user-{i}", "tier": "standard"} for i in range(1, 21)
}
_flags = FeatureFlags(file_path=os.environ.get("FEATURE_FLAGS_PATH"))
_log = get_logger("user_service")
_meter = metrics.get_meter("user_service")
_lookups = _meter.create_counter(
    "user_lookups_total",
    description="Total user lookup attempts",
)
_auth_checks = _meter.create_counter(
    "user_auth_checks_total",
    description="Total auth checks",
)

app = FastAPI(title="user-service")
_log.info("user-service started")


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/api/users")
async def list_users() -> dict:
    _lookups.add(1, {"op": "list"})
    return {"users": list(_users.values())}


@app.get("/api/users/{user_id}")
async def get_user(user_id: str) -> dict:
    _lookups.add(1, {"op": "get"})
    user = _users.get(user_id)
    if user is None:
        log_event(
            _log,
            BizEvent.USER_AUTH_FAILED,
            f"unknown user {user_id}",
            user_id=user_id,
            reason="not_found",
        )
        raise HTTPException(status_code=404, detail="user not found")
    return user


@app.get("/api/users/{user_id}/authcheck")
async def authcheck(user_id: str) -> dict:
    """Synthetic endpoint that order-service calls before accepting an order.
    Occasionally fails to simulate auth flakiness — gives the agent something
    to find in logs when correlating with order-service errors."""
    _auth_checks.add(1, {})
    if user_id not in _users:
        log_event(
            _log,
            BizEvent.USER_AUTH_FAILED,
            f"auth failed for {user_id}: unknown user",
            user_id=user_id,
            reason="not_found",
        )
        raise HTTPException(status_code=401, detail="unauthorized")

    if random.random() < 0.005:
        log_event(
            _log,
            BizEvent.USER_AUTH_FAILED,
            f"auth check transient failure for {user_id}",
            user_id=user_id,
            reason="transient",
        )
        raise HTTPException(status_code=503, detail="auth temporarily unavailable")

    log_event(
        _log,
        BizEvent.USER_LOGGED_IN,
        f"auth check passed for {user_id}",
        user_id=user_id,
    )
    return {"user_id": user_id, "ok": True}
