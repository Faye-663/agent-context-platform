from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent_context_platform.indexers import (
    index_java_source,
    index_java_symbols,
    index_markdown_document,
    index_sql_ddl,
    index_sql_symbols,
)
from agent_context_platform.models import AssetType, SourceType
from agent_context_platform.storage import Base, IndexedItemRepository


JAVA_SAMPLE = """package example;

@Service
public class PaymentMessageBuilder {
    @Trace
    public String build(PaymentRequest request) {
        return "ok";
    }
}
"""

JAVA_SYMBOL_SAMPLE = """package example;

interface PaymentHandler {
    String handle(PaymentRequest request);
}

enum PaymentStatus {
    CREATED, PAID
}

@interface Audited {
    String value();
}

record PaymentRecord(String id) {
    PaymentRecord {
    }
}

class PaymentService {
    private String status;

    PaymentService() {
    }

    String build(PaymentRequest request) {
        return status;
    }
}
"""


SQL_SAMPLE = """CREATE TABLE payment_order (
    id BIGINT PRIMARY KEY,
    status VARCHAR(32) NOT NULL,
    amount DECIMAL(18, 2)
);

CREATE INDEX idx_payment_order_status ON payment_order (status);
"""


MARKDOWN_SAMPLE = """# Payment Integration

Overview for payment integration.

## Message Generation

Build payment messages from order data.

### Error Handling

Map provider errors to internal status.
"""


def test_java_indexer_extracts_class_method_annotations_signature_and_lines() -> None:
    items = index_java_source(
        path="src/main/java/example/PaymentMessageBuilder.java",
        content=JAVA_SAMPLE,
    )

    class_item = next(item for item in items if item.metadata["symbol_type"] == "class")
    method_item = next(item for item in items if item.metadata["symbol_type"] == "method")

    assert class_item.asset_type is AssetType.CODE
    assert class_item.title == "PaymentMessageBuilder"
    assert class_item.metadata["language"] == "java"
    assert class_item.metadata["annotations"] == ["Service"]
    assert class_item.metadata["signature"] == "public class PaymentMessageBuilder"
    assert class_item.source.source_type is SourceType.CODE
    assert class_item.source.path == "src/main/java/example/PaymentMessageBuilder.java"
    assert class_item.source.start_line == 3
    assert class_item.source.end_line == 9
    assert class_item.source.symbol == "PaymentMessageBuilder"

    assert method_item.title == "PaymentMessageBuilder.build"
    assert method_item.metadata["annotations"] == ["Trace"]
    assert method_item.metadata["signature"] == "public String build(PaymentRequest request)"
    assert method_item.source.start_line == 5
    assert method_item.source.end_line == 8
    assert method_item.source.symbol == "PaymentMessageBuilder.build"


def test_java_symbol_catalog_extracts_graph_foundation_declarations() -> None:
    symbols = index_java_symbols(
        path="src/main/java/example/PaymentService.java",
        content=JAVA_SYMBOL_SAMPLE,
        repo="gitlab.example.com/payments/payment-service",
    )

    by_kind_name = {(symbol.kind, symbol.name): symbol for symbol in symbols}

    assert by_kind_name[("interface", "PaymentHandler")].qualified_name == (
        "example.PaymentHandler"
    )
    assert by_kind_name[("method", "handle")].qualified_name == (
        "example.PaymentHandler.handle(PaymentRequest)"
    )
    assert by_kind_name[("enum", "PaymentStatus")].qualified_name == (
        "example.PaymentStatus"
    )
    assert by_kind_name[("annotation_type", "Audited")].qualified_name == (
        "example.Audited"
    )
    assert by_kind_name[("record", "PaymentRecord")].qualified_name == (
        "example.PaymentRecord"
    )
    assert by_kind_name[("constructor", "PaymentService")].qualified_name == (
        "example.PaymentService.<init>()"
    )
    assert by_kind_name[("field", "status")].qualified_name == (
        "example.PaymentService.status"
    )
    assert by_kind_name[("method", "build")].qualified_name == (
        "example.PaymentService.build(PaymentRequest)"
    )
    assert all(symbol.repo == "gitlab.example.com/payments/payment-service" for symbol in symbols)
    assert all(symbol.path == "src/main/java/example/PaymentService.java" for symbol in symbols)
    assert all(symbol.symbol_id.startswith("java:") for symbol in symbols)


def test_java_indexer_creates_display_items_for_every_catalog_symbol() -> None:
    path = "src/main/java/example/PaymentService.java"
    items = index_java_source(path=path, content=JAVA_SYMBOL_SAMPLE, repo="example/repo")
    symbols = index_java_symbols(
        path=path,
        content=JAVA_SYMBOL_SAMPLE,
        repo="example/repo",
        indexed_items=items,
    )

    assert all(symbol.source_item_id is not None for symbol in symbols)


def test_sql_indexer_extracts_table_columns_indexes_and_source() -> None:
    items = index_sql_ddl(path="schema/payment.sql", content=SQL_SAMPLE)

    table_item = next(item for item in items if item.metadata["symbol_type"] == "table")
    status_column = next(
        item for item in items if item.metadata["symbol_type"] == "column" and item.source.column == "status"
    )

    assert table_item.asset_type is AssetType.DB_SCHEMA
    assert table_item.title == "payment_order"
    assert table_item.metadata["columns"] == ["id", "status", "amount"]
    assert table_item.metadata["indexes"] == ["idx_payment_order_status"]
    assert table_item.source.source_type is SourceType.DB_SCHEMA
    assert table_item.source.path == "schema/payment.sql"
    assert table_item.source.table == "payment_order"

    assert status_column.title == "payment_order.status"
    assert status_column.metadata["data_type"] == "VARCHAR(32)"
    assert status_column.source.table == "payment_order"
    assert status_column.source.column == "status"


def test_sql_symbol_catalog_extracts_table_and_columns() -> None:
    symbols = index_sql_symbols(
        path="schema/payment.sql",
        content=SQL_SAMPLE,
        repo="gitlab.example.com/payments/payment-service",
    )

    by_qualified_name = {symbol.qualified_name: symbol for symbol in symbols}

    assert by_qualified_name["payment_order"].kind == "table"
    assert by_qualified_name["payment_order.status"].kind == "column"
    assert by_qualified_name["payment_order.status"].symbol_id == (
        "sql:column:payment_order.status"
    )


def test_markdown_indexer_extracts_heading_path_body_and_lines() -> None:
    items = index_markdown_document(path="docs/payment.md", content=MARKDOWN_SAMPLE)

    section = next(item for item in items if item.title == "Message Generation")
    child_section = next(item for item in items if item.title == "Error Handling")

    assert section.asset_type is AssetType.DOC
    assert section.metadata["heading_path"] == "Payment Integration > Message Generation"
    assert "Build payment messages" in section.content
    assert section.source.source_type is SourceType.DOC
    assert section.source.path == "docs/payment.md"
    assert section.source.heading_path == "Payment Integration > Message Generation"
    assert section.source.start_line == 5
    assert section.source.end_line == 7

    assert child_section.metadata["heading_path"] == (
        "Payment Integration > Message Generation > Error Handling"
    )
    assert child_section.source.start_line == 9
    assert child_section.source.end_line == 11


def test_offline_index_results_can_be_saved_to_repository() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    items = (
        index_java_source(
            "src/main/java/example/PaymentMessageBuilder.java",
            JAVA_SAMPLE,
            repo="gitlab.example.com/payments/payment-service",
        )
        + index_sql_ddl(
            "schema/payment.sql",
            SQL_SAMPLE,
            repo="gitlab.example.com/payments/payment-service",
        )
        + index_markdown_document(
            "docs/payment.md",
            MARKDOWN_SAMPLE,
            repo="gitlab.example.com/payments/payment-service",
        )
    )

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        for item in items:
            repository.save(item)
        session.commit()

    with Session(engine) as session:
        repository = IndexedItemRepository(session)

        assert repository.list(
            asset_type=AssetType.CODE,
            repo="gitlab.example.com/payments/payment-service",
        )
        assert repository.list(
            asset_type=AssetType.DB_SCHEMA,
            repo="gitlab.example.com/payments/payment-service",
        )
        assert repository.list(
            asset_type=AssetType.DOC,
            repo="gitlab.example.com/payments/payment-service",
        )
