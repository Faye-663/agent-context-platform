from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


def _load_script_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "verify_phase2_e2e_sqlite.py"
    )
    spec = importlib.util.spec_from_file_location("verify_phase2_e2e_sqlite", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase2_e2e_script_persists_indexed_items_to_file_sqlite(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    sample_root = tmp_path / "phase2-e2e"
    (sample_root / "src/main/java/example").mkdir(parents=True)
    (sample_root / "schema").mkdir()
    (sample_root / "docs").mkdir()
    (sample_root / "src/main/java/example/PaymentMessageBuilder.java").write_text(
        """package example;

@Service
public class PaymentMessageBuilder {
    @Trace
    public String build(PaymentRequest request) {
        return "ok";
    }
}
""",
        encoding="utf-8",
    )
    (sample_root / "schema/payment.sql").write_text(
        """CREATE TABLE payment_order (
    id BIGINT PRIMARY KEY,
    status VARCHAR(32) NOT NULL,
    amount DECIMAL(18, 2)
);

CREATE INDEX idx_payment_order_status ON payment_order (status);
""",
        encoding="utf-8",
    )
    (sample_root / "docs/payment.md").write_text(
        """# Payment Integration

Overview for payment integration.

## Message Generation

Build payment messages from order data.

### Error Handling

Map provider errors to internal status.
""",
        encoding="utf-8",
    )
    sqlite_db = sample_root / "indexed-items.sqlite"

    result = module.verify_phase2_e2e(sample_root=sample_root, sqlite_db=sqlite_db)

    assert result["status"] == "PASS"
    assert result["indexed_total"] == 9
    assert result["persisted_counts"] == {"code": 2, "db_schema": 4, "doc": 3}
    assert result["sqlite_db"] == str(sqlite_db)
    assert sqlite_db.exists()

    with sqlite3.connect(sqlite_db) as connection:
        rows = connection.execute(
            "select asset_type, count(*) from indexed_items group by asset_type"
        ).fetchall()
    assert sorted(rows) == [("code", 2), ("db_schema", 4), ("doc", 3)]


def test_phase2_e2e_script_reuses_existing_sqlite_file(tmp_path: Path) -> None:
    module = _load_script_module()
    sample_root = tmp_path / "phase2-e2e"
    (sample_root / "src/main/java/example").mkdir(parents=True)
    (sample_root / "schema").mkdir()
    (sample_root / "docs").mkdir()
    (sample_root / "src/main/java/example/PaymentMessageBuilder.java").write_text(
        """package example;

public class PaymentMessageBuilder {
    public String build(PaymentRequest request) {
        return "ok";
    }
}
""",
        encoding="utf-8",
    )
    (sample_root / "schema/payment.sql").write_text(
        "CREATE TABLE payment_order (id BIGINT PRIMARY KEY);",
        encoding="utf-8",
    )
    (sample_root / "docs/payment.md").write_text(
        "# Payment Integration\n\n## Message Generation\n\nBuild payment messages.",
        encoding="utf-8",
    )
    sqlite_db = sample_root / "indexed-items.sqlite"
    with sqlite3.connect(sqlite_db) as connection:
        connection.execute("create table local_note (value text)")
        connection.execute("insert into local_note values ('keep me')")

    module.verify_phase2_e2e(sample_root=sample_root, sqlite_db=sqlite_db)

    with sqlite3.connect(sqlite_db) as connection:
        note = connection.execute("select value from local_note").fetchone()
    assert note == ("keep me",)
