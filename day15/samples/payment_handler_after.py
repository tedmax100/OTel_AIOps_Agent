"""照 MCP 查到的定義改過的版本。

四個改動的依據都來自 MCP 的回應，不是猜的：
- payment.transaction_id  ← get_attribute("payment.id") 的 deprecated.renamed_to
- payment.method          ← search("payment") 裡唯一還活著的支付方式欄位
- outcome 不做 .upper()   ← search 結果帶回來的 enum members 是小寫
- retry_count 不再當 attribute ← live_check 說它 missing_attribute（base 0.2.0 已移除）
"""

from opentelemetry import trace

tracer = trace.get_tracer(__name__)


def call_gateway(cents: int) -> str:
    """假的金流商：奇數分就被拒（跟 demo stack 的 decline 觸發條件一致）。"""
    return "declined" if cents % 2 else "authorized"


def charge(order_id: str, cents: int, retries: int = 0) -> str:
    with tracer.start_as_current_span("charge") as span:
        outcome = call_gateway(cents)
        span.set_attribute("payment.transaction_id", f"pay-{order_id}")  # renamed_to 指定的新名字
        span.set_attribute("payment.method", "credit_card")              # 取代 payment.gateway
        span.set_attribute("payment.outcome", outcome)                   # enum members 裡的原樣值
        # payment.retry_count 在 registry 裡已不存在：改記在 span event 上，不再當 attribute
        if retries:
            span.add_event("payment.retried", {"retry.count": retries})
        return outcome
