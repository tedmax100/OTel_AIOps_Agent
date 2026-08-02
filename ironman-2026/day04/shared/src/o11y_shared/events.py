from enum import StrEnum


class BizEvent(StrEnum):
    """Low-cardinality biz event enum. Add new members deliberately — every
    addition widens the label space for `sum by (event)` queries.

    Naming: `<domain>.<verb_past_tense>` or `<domain>.<state>`.
    Never include dynamic ids (order_id, user_id) here — those go in the log
    message body, not the event label."""

    # payment domain
    PAYMENT_REQUESTED = "payment.requested"
    PAYMENT_AUTHORIZED = "payment.authorized"
    PAYMENT_DECLINED = "payment.declined"
    PAYMENT_REFUNDED = "payment.refunded"
    PAYMENT_GATEWAY_ERROR = "payment.gateway_error"

    # order domain
    ORDER_CREATED = "order.created"
    ORDER_UPDATED = "order.updated"
    ORDER_CANCELLED = "order.cancelled"

    # user domain
    USER_LOGGED_IN = "user.logged_in"
    USER_REGISTERED = "user.registered"
    USER_AUTH_FAILED = "user.auth_failed"

    # gateway / webapp
    REQUEST_RECEIVED = "http.request_received"
    REQUEST_FAILED = "http.request_failed"

    # infrastructure-ish but still biz-flavored
    CACHE_MISS = "cache.miss"
    DEPLOYMENT_STARTED = "deployment.started"
