"""沒過治理的版本：四個欄位名稱，四種不同的問題。

每一行都情有可原：`paymentId` 是隔壁服務的慣例、`payment.gateway` 半年前是對的、
`.upper()` 是為了 dashboard 好看、`retry_count` 是上一版 registry 有的欄位。
"""

from opentelemetry import trace

tracer = trace.get_tracer(__name__)


def call_gateway(cents: int) -> str:
    """假的金流商：奇數分就被拒（跟 demo stack 的 decline 觸發條件一致）。"""
    return "declined" if cents % 2 else "authorized"


def charge(order_id: str, cents: int, retries: int = 0) -> str:
    with tracer.start_as_current_span("charge") as span:
        outcome = call_gateway(cents)
        span.set_attribute("paymentId", f"pay-{order_id}")       # 沒有 namespace、camelCase
        span.set_attribute("payment.gateway", "stripe")          # base 0.2.0 已 obsoleted
        span.set_attribute("payment.outcome", outcome.upper())   # 值域大小寫不符
        span.set_attribute("payment.retry_count", retries)       # base 0.2.0 已移除
        return outcome
