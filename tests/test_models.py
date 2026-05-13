from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_context_platform.models import (
    AssetType,
    IndexedItem,
    SearchResult,
    SourceCitation,
    SourceType,
    TaskContext,
)


def test_source_citation_supports_code_sql_and_markdown_sources() -> None:
    code = SourceCitation(
        source_type=SourceType.CODE,
        path="src/main/java/example/PaymentMessageBuilder.java",
        start_line=12,
        end_line=34,
        symbol="PaymentMessageBuilder.build",
    )
    sql = SourceCitation(source_type=SourceType.DB_SCHEMA, table="payment_order")
    doc = SourceCitation(
        source_type=SourceType.DOC,
        path="docs/design/payment-integration.md",
        start_line=8,
        end_line=20,
        heading_path="Payment Integration > Message Generation",
    )

    assert code.path == "src/main/java/example/PaymentMessageBuilder.java"
    assert sql.table == "payment_order"
    assert doc.heading_path == "Payment Integration > Message Generation"


def test_code_source_requires_file_and_line_range() -> None:
    with pytest.raises(ValidationError):
        SourceCitation(source_type=SourceType.CODE, path="src/Example.java")


def test_search_result_rejects_missing_or_mismatched_source() -> None:
    source = SourceCitation(
        source_type=SourceType.CODE,
        path="src/main/java/example/PaymentMessageBuilder.java",
        start_line=12,
        end_line=34,
        symbol="PaymentMessageBuilder.build",
    )
    item = IndexedItem(
        id="code:PaymentMessageBuilder.build",
        asset_type=AssetType.CODE,
        title="PaymentMessageBuilder.build",
        content="build payment message",
        summary="构造支付报文的示例方法。",
        metadata={"language": "java", "symbol_type": "method"},
        source=source,
    )

    with pytest.raises(ValidationError):
        SearchResult(item=item, score=0.82, match_reason="keyword hit")

    other_source = SourceCitation(
        source_type=SourceType.CODE,
        path="src/main/java/example/Other.java",
        start_line=1,
        end_line=2,
        symbol="Other.build",
    )
    with pytest.raises(ValidationError):
        SearchResult(
            item=item,
            score=0.82,
            match_reason="keyword hit",
            source=other_source,
        )


def test_json_serialization_matches_context_api_contract_shape() -> None:
    source = SourceCitation(
        source_type=SourceType.CODE,
        path="src/main/java/example/PaymentMessageBuilder.java",
        start_line=32,
        end_line=88,
        symbol="PaymentMessageBuilder.build",
    )
    item = IndexedItem(
        id="code:example:PaymentMessageBuilder",
        asset_type=AssetType.CODE,
        title="PaymentMessageBuilder.build",
        content="payment message build implementation",
        summary="构造支付报文的示例方法。",
        metadata={
            "language": "java",
            "symbol_type": "method",
            "signature": "build(PaymentRequest request)",
        },
        source=source,
    )
    result = SearchResult(
        item=item,
        score=0.82,
        match_reason="方法名和正文同时命中 payment/message/build",
        source=source,
    )

    payload = result.model_dump(mode="json")

    assert payload["item"]["asset_type"] == "code"
    assert payload["item"]["source"]["path"] == "src/main/java/example/PaymentMessageBuilder.java"
    assert payload["source"]["symbol"] == "PaymentMessageBuilder.build"


def test_task_context_requires_citation_summary_for_all_results() -> None:
    source = SourceCitation(
        source_type=SourceType.DOC,
        path="docs/design/payment-integration.md",
        start_line=1,
        end_line=5,
        heading_path="Payment Integration",
    )
    item = IndexedItem(
        id="doc:payment-integration",
        asset_type=AssetType.DOC,
        title="Payment Integration",
        content="payment integration design",
        summary="支付集成设计说明。",
        metadata={},
        source=source,
    )
    result = SearchResult(
        item=item,
        score=0.7,
        match_reason="heading hit",
        source=source,
    )

    with pytest.raises(ValidationError):
        TaskContext(query="新增支付接口", related_docs=[result], citations=[])

    context = TaskContext(
        query="新增支付接口",
        related_docs=[result],
        citations=[source],
    )
    assert context.related_docs[0].source == source
