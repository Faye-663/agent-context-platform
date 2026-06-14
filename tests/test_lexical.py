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
    assert "现金流" in token_set.tokens
    assert "审批" in token_set.tokens
    assert "PaymentMessageBuilder.build" in token_set.symbol_terms


def test_tokenize_query_uses_word_level_chinese_segmentation() -> None:
    token_set = tokenize_query(
        "现金流审批状态流转和资金安全风险点",
        domain_terms=("现金流审批", "状态流转", "资金安全"),
    )

    assert "现金流审批" in token_set.tokens
    assert "现金流" in token_set.tokens
    assert "审批" in token_set.tokens
    assert "状态流转" in token_set.tokens
    assert "状态" in token_set.tokens
    assert "流转" in token_set.tokens
    assert "资金安全" in token_set.tokens
    assert "风险点" in token_set.tokens
    assert "流审" not in token_set.tokens
