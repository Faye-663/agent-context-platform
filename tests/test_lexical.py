from __future__ import annotations

from agent_context_platform.lexical import tokenize_query


def test_tokenize_query_handles_code_symbols_and_chinese_domain_terms() -> None:
    token_set = tokenize_query(
        "PaymentMessageBuilder.build 现金流审批",
        domain_terms=("现金流审批",),
    )

    assert "paymentmessagebuilder.build" in token_set.tokens
    assert "payment" in token_set.tokens
    assert "message" in token_set.tokens
    assert "builder" in token_set.tokens
    assert "现金流审批" in token_set.tokens
    assert "现金" in token_set.tokens
    assert "PaymentMessageBuilder.build" in token_set.symbol_terms
