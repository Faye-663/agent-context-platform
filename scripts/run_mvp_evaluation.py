from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agent_context_platform.api import create_app
from agent_context_platform.evaluation import (
    EvaluationSample,
    evaluate_context_payloads,
)
from agent_context_platform.models import AssetType, IndexedItem, SourceCitation, SourceType
from agent_context_platform.retrieval import HybridSearchService
from agent_context_platform.storage import Base, IndexedItemRepository


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLES_PATH = (
    ROOT / "docs" / "archive" / "mvp" / "evaluation" / "mvp-evaluation-samples.json"
)


def main() -> None:
    # 这是固定样本回归评测脚本，不是线上检索入口；线上请求仍走 FastAPI/MCP。
    args = _parse_args()
    samples = _load_samples(args.samples)
    client = _make_seeded_client()
    payloads = {
        sample.id: _post_build_task_context(client, sample)
        for sample in samples
    }
    report = evaluate_context_payloads(samples, payloads)
    print(report.model_dump_json(indent=2))
    if not report.passed:
        raise SystemExit(1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the archived MVP context retrieval regression evaluation."
    )
    parser.add_argument(
        "--samples",
        type=Path,
        default=DEFAULT_SAMPLES_PATH,
        help="Path to the evaluation sample JSON file.",
    )
    return parser.parse_args()


def _load_samples(path: Path) -> list[EvaluationSample]:
    with path.open("r", encoding="utf-8") as file:
        raw_samples = json.load(file)
    return [EvaluationSample.model_validate(sample) for sample in raw_samples]


def _make_seeded_client() -> TestClient:
    # 评测用内存 SQLite 和脱敏样本，目的是稳定比较召回质量，不依赖本机 PostgreSQL。
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    repository = IndexedItemRepository(session)
    _seed_evaluation_corpus(repository)
    session.commit()
    return TestClient(create_app(HybridSearchService(repository)))


def _post_build_task_context(
    client: TestClient, sample: EvaluationSample
) -> dict[str, Any]:
    response = client.post(
        "/build-task-context",
        json={
            "task": sample.task,
            "limits": {
                "code": 5,
                "db_schema": 5,
                "docs": 5,
                "similar_implementations": 5,
            },
            "constraints": {"language": "java"},
            "request_id": f"eval-{sample.id}",
        },
    )
    response.raise_for_status()
    return response.json()


def _seed_evaluation_corpus(repository: IndexedItemRepository) -> None:
    # 这里直接写 IndexedItem，跳过 indexers，便于评测集专注检索排序和上下文组装。
    for item in _evaluation_items():
        repository.save(item, embedding=[1.0, 0.0, 0.0])


def _evaluation_items() -> list[IndexedItem]:
    return [
        _code_item(
            item_id="code:PaymentMessageBuilder.build",
            title="PaymentMessageBuilder.build",
            content="payment message build order amount integration",
            path="src/main/java/example/PaymentMessageBuilder.java",
            symbol="PaymentMessageBuilder.build",
        ),
        _code_item(
            item_id="code:RefundMessageBuilder.build",
            title="RefundMessageBuilder.build",
            content="refund message build refund order reason status",
            path="src/main/java/example/RefundMessageBuilder.java",
            symbol="RefundMessageBuilder.build",
        ),
        _code_item(
            item_id="code:RiskRuleEngine.evaluate",
            title="RiskRuleEngine.evaluate",
            content="risk rule evaluate order amount decision reason",
            path="src/main/java/example/RiskRuleEngine.java",
            symbol="RiskRuleEngine.evaluate",
        ),
        _code_item(
            item_id="code:CustomerProfileService.update",
            title="CustomerProfileService.update",
            content="customer profile update rule contact address",
            path="src/main/java/example/CustomerProfileService.java",
            symbol="CustomerProfileService.update",
        ),
        _code_item(
            item_id="code:InvoiceExportService.export",
            title="InvoiceExportService.export",
            content="invoice export status file generation",
            path="src/main/java/example/InvoiceExportService.java",
            symbol="InvoiceExportService.export",
        ),
        _code_item(
            item_id="code:AccountQueryService.query",
            title="AccountQueryService.query",
            content="account balance query customer account",
            path="src/main/java/example/AccountQueryService.java",
            symbol="AccountQueryService.query",
        ),
        _schema_item(
            item_id="db_schema:payment_order",
            title="payment_order",
            content="payment order status amount integration message",
            table="payment_order",
        ),
        _schema_item(
            item_id="db_schema:refund_order",
            title="refund_order",
            content="refund order status reason amount",
            table="refund_order",
        ),
        _schema_item(
            item_id="db_schema:risk_event",
            title="risk_event",
            content="risk event schema decision reason order amount",
            table="risk_event",
        ),
        _schema_item(
            item_id="db_schema:customer_profile",
            title="customer_profile",
            content="customer profile update contact address",
            table="customer_profile",
        ),
        _doc_item(
            item_id="doc:payment-integration-message-generation",
            title="Payment Integration Message Generation",
            content="payment integration message generation build order amount",
            path="docs/payment-integration.md",
            heading_path="Payment Integration > Message Generation",
        ),
        _doc_item(
            item_id="doc:refund-processing-message-generation",
            title="Refund Processing Message Generation",
            content="refund processing message generation status reason",
            path="docs/refund-processing.md",
            heading_path="Refund Processing > Message Generation",
        ),
        _doc_item(
            item_id="doc:risk-review-decision-rule",
            title="Risk Review Decision Rule",
            content="risk review decision rule event schema reason",
            path="docs/risk-review.md",
            heading_path="Risk Review > Decision Rule",
        ),
        _doc_item(
            item_id="doc:customer-profile-update-rule",
            title="Customer Profile Update Rule",
            content="customer profile document update rule contact address",
            path="docs/customer-profile.md",
            heading_path="Customer Profile > Update Rule",
        ),
    ]


def _code_item(
    *,
    item_id: str,
    title: str,
    content: str,
    path: str,
    symbol: str,
) -> IndexedItem:
    return IndexedItem(
        id=item_id,
        asset_type=AssetType.CODE,
        title=title,
        content=content,
        summary=f"{title} desensitized evaluation code sample.",
        metadata={"language": "java", "symbol_type": "method"},
        source=SourceCitation(
            source_type=SourceType.CODE,
            path=path,
            start_line=10,
            end_line=30,
            symbol=symbol,
        ),
    )


def _schema_item(
    *, item_id: str, title: str, content: str, table: str
) -> IndexedItem:
    return IndexedItem(
        id=item_id,
        asset_type=AssetType.DB_SCHEMA,
        title=title,
        content=content,
        summary=f"{title} desensitized evaluation schema sample.",
        metadata={"symbol_type": "table", "table": table},
        source=SourceCitation(source_type=SourceType.DB_SCHEMA, table=table),
    )


def _doc_item(
    *,
    item_id: str,
    title: str,
    content: str,
    path: str,
    heading_path: str,
) -> IndexedItem:
    return IndexedItem(
        id=item_id,
        asset_type=AssetType.DOC,
        title=title,
        content=content,
        summary=f"{title} desensitized evaluation doc sample.",
        metadata={"heading_path": heading_path},
        source=SourceCitation(
            source_type=SourceType.DOC,
            path=path,
            start_line=1,
            end_line=12,
            heading_path=heading_path,
        ),
    )


if __name__ == "__main__":
    main()
