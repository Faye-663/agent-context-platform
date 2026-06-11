from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_context_platform.models import (
    AssetType,
    IndexedItem,
    SearchResult,
    SourceCitation,
    SourceType,
    SymbolCatalogEntry,
    TaskContext,
)


def test_source_citation_supports_code_sql_and_markdown_sources() -> None:
    indexed_at = datetime(2026, 6, 10, 8, 30, tzinfo=UTC)
    code = SourceCitation(
        source_type=SourceType.CODE,
        repo="payment-service",
        branch="main",
        commit_sha="abc123",
        file_hash="f" * 64,
        indexed_at=indexed_at,
        index_batch_id="batch-001",
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
    assert code.branch == "main"
    assert code.commit_sha == "abc123"
    assert code.file_hash == "f" * 64
    assert code.indexed_at == indexed_at
    assert code.index_batch_id == "batch-001"
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


def test_source_citation_serializes_provenance_fields() -> None:
    source = SourceCitation(
        source_type=SourceType.CODE,
        repo="payment-service",
        branch="main",
        commit_sha="abc123",
        file_hash="f" * 64,
        indexed_at=datetime(2026, 6, 10, 8, 30, tzinfo=UTC),
        index_batch_id="batch-001",
        path="src/main/java/example/PaymentMessageBuilder.java",
        start_line=32,
        end_line=88,
        symbol="PaymentMessageBuilder.build",
    )

    payload = source.model_dump(mode="json")

    assert payload["branch"] == "main"
    assert payload["commit_sha"] == "abc123"
    assert payload["file_hash"] == "f" * 64
    assert payload["indexed_at"] == "2026-06-10T08:30:00Z"
    assert payload["index_batch_id"] == "batch-001"


def test_symbol_catalog_entry_serializes_identity_and_provenance() -> None:
    indexed_at = datetime(2026, 6, 10, 8, 30, tzinfo=UTC)

    symbol = SymbolCatalogEntry(
        symbol_id="java:method:example.PaymentService.build(PaymentRequest)",
        repo="gitlab.example.com/payments/payment-service",
        path="src/main/java/example/PaymentService.java",
        language="java",
        kind="method",
        name="build",
        qualified_name="example.PaymentService.build(PaymentRequest)",
        start_line=12,
        end_line=18,
        source_item_id="code:src/main/java/example/PaymentService.java:PaymentService.build",
        branch="main",
        commit_sha="abc123",
        file_hash="f" * 64,
        indexed_at=indexed_at,
        index_batch_id="batch-001",
    )

    payload = symbol.model_dump(mode="json")

    assert payload["symbol_id"] == "java:method:example.PaymentService.build(PaymentRequest)"
    assert payload["repo"] == "gitlab.example.com/payments/payment-service"
    assert payload["qualified_name"] == "example.PaymentService.build(PaymentRequest)"
    assert payload["indexed_at"] == "2026-06-10T08:30:00Z"


def test_symbol_catalog_entry_rejects_invalid_line_range() -> None:
    with pytest.raises(ValidationError):
        SymbolCatalogEntry(
            symbol_id="java:field:example.PaymentService.status",
            repo="gitlab.example.com/payments/payment-service",
            path="src/main/java/example/PaymentService.java",
            language="java",
            kind="field",
            name="status",
            qualified_name="example.PaymentService.status",
            start_line=20,
            end_line=12,
        )


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
