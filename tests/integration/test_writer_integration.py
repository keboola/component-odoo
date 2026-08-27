"""
Integration tests for the Odoo writer against a live local Odoo instance.

Run with:
    pytest tests/integration/test_writer_integration.py -v

Requires docker-compose.test.yml to be running (handled by the `odoo` fixture).
Tests run against both XML-RPC and JSON-2 protocols.
"""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from extractor_component import Component as ExtractorComponent
from writer_component import Component as WriterComponent

from .conftest import OdooConfig, read_csv, write_config, write_input_csv

pytestmark = pytest.mark.timeout(120)

# Unique tag prefix per test run so records can be found reliably
RUN_TAG = uuid.uuid4().hex[:8]


def extractor_params(
    odoo: OdooConfig, protocol: str, model: str, fields: list[str], like: str | None = None
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "odoo_url": odoo.odoo_url,
        "database": odoo.database,
        "username": odoo.username,
        "#api_key": odoo.api_key,
        "api_protocol": protocol,
        "model": model,
        "fields": fields,
        "incremental": False,
    }
    if like:
        params["domain"] = json.dumps([["name", "like", like]])
    return params


def writer_params(odoo: OdooConfig, protocol: str, model: str, input_table: str, **kwargs) -> dict[str, Any]:
    return {
        "odoo_url": odoo.odoo_url,
        "database": odoo.database,
        "username": odoo.username,
        "#api_key": odoo.api_key,
        "api_protocol": protocol,
        "model": model,
        "input_table": input_table,
        "batch_size": 100,
        **kwargs,
    }


def run_writer(kbc_datadir: Path, params: dict, rows: list[dict], storage: dict | None = None) -> Path:
    filename = params["input_table"]
    write_input_csv(kbc_datadir, filename, rows)
    write_config(kbc_datadir, params, storage=storage)
    WriterComponent().run()
    return kbc_datadir


def run_extractor(kbc_datadir: Path, params: dict) -> list[dict]:
    write_config(kbc_datadir, params)
    ExtractorComponent().run()
    csv_path = kbc_datadir / "out" / "tables" / f"{params['model'].replace('.', '_')}.csv"
    if not csv_path.exists():
        return []
    return read_csv(kbc_datadir, params["model"].replace(".", "_"))


class TestWriterXmlRpc:
    PROTOCOL = "xmlrpc"

    def _proto_tag(self) -> str:
        """Unique tag per protocol to avoid cross-protocol record collisions."""
        return f"{RUN_TAG}-{self.PROTOCOL[:4]}"

    def _run_sync_action(self, kbc_datadir: Path, action: str, params: dict, storage: dict | None = None) -> Any:
        """Run a writer sync action and return the parsed JSON result."""
        import io
        import sys

        config: dict = {"action": action, "parameters": params}
        if storage:
            config["storage"] = storage
        (kbc_datadir / "config.json").write_text(json.dumps(config))
        captured = io.StringIO()
        sys.stdout = captured
        try:
            WriterComponent().execute_action()
        finally:
            sys.stdout = sys.__stdout__
        for line in reversed(captured.getvalue().splitlines()):
            line = line.strip()
            if line.startswith("{") or line.startswith("["):
                return json.loads(line)
        raise AssertionError(f"No JSON found in output: {captured.getvalue()!r}")

    def test_writes_records_and_verifies_via_extractor(self, odoo, kbc_datadir):
        """Write 3 partners, extract them back, verify they appear."""
        tag = self._proto_tag()
        names = [f"ITG-{tag}-basic-{i}" for i in range(3)]
        rows = [{"name": n, "email": f"{n}@test.com"} for n in names]

        run_writer(kbc_datadir, writer_params(odoo, self.PROTOCOL, "res.partner", "partners.csv"), rows)

        extracted = run_extractor(
            kbc_datadir,
            extractor_params(odoo, self.PROTOCOL, "res.partner", ["id", "name", "email"], like=f"ITG-{tag}-basic-"),
        )
        extracted_names = {r["name"] for r in extracted}
        assert all(n in extracted_names for n in names)

    def test_batching_writes_all_records(self, odoo, kbc_datadir):
        """150 records written in 2 batches of 100 — all arrive in Odoo."""
        tag = self._proto_tag()
        rows = [{"name": f"ITG-{tag}-batch-{i}"} for i in range(150)]
        params = writer_params(odoo, self.PROTOCOL, "res.partner", "partners.csv", batch_size=100)

        run_writer(kbc_datadir, params, rows)

        extracted = run_extractor(
            kbc_datadir,
            extractor_params(odoo, self.PROTOCOL, "res.partner", ["id", "name"], like=f"ITG-{tag}-batch-"),
        )
        assert len(extracted) == 150

    def test_field_mapping_renames_columns(self, odoo, kbc_datadir):
        """CSV columns renamed via field_mapping arrive under Odoo field names."""
        tag = self._proto_tag()
        rows = [{"csv_name": f"ITG-{tag}-mapped", "csv_email": "mapped@test.com"}]
        params = writer_params(
            odoo,
            self.PROTOCOL,
            "res.partner",
            "partners.csv",
            field_mapping=[
                {"source_column": "csv_name", "destination_field": "name"},
                {"source_column": "csv_email", "destination_field": "email"},
            ],
        )

        run_writer(kbc_datadir, params, rows)

        extracted = run_extractor(
            kbc_datadir,
            extractor_params(odoo, self.PROTOCOL, "res.partner", ["id", "name", "email"], like=f"ITG-{tag}-mapped"),
        )
        assert len(extracted) == 1
        assert extracted[0]["email"] == "mapped@test.com"

    def test_continue_on_error_does_not_raise(self, odoo, kbc_datadir):
        """With continue_on_error=True, the run completes even if individual batches fail."""
        tag = self._proto_tag()
        rows = [
            {"name": f"ITG-{tag}-coe-1"},
            {"name": f"ITG-{tag}-coe-2"},
        ]
        params = writer_params(
            odoo,
            self.PROTOCOL,
            "res.partner",
            "partners.csv",
            batch_size=1,
            continue_on_error=True,
        )

        # Should not raise even with small batches
        run_writer(kbc_datadir, params, rows)

        extracted = run_extractor(
            kbc_datadir,
            extractor_params(odoo, self.PROTOCOL, "res.partner", ["id", "name"], like=f"ITG-{tag}-coe-"),
        )
        assert len(extracted) >= 1

    def test_sync_list_input_tables(self, odoo, kbc_datadir):
        """listInputTables returns tables from input mapping."""
        write_input_csv(kbc_datadir, "partners.csv", [{"name": "test"}])
        result = self._run_sync_action(
            kbc_datadir,
            "listInputTables",
            writer_params(odoo, self.PROTOCOL, "res.partner", "partners.csv"),
            storage={"input": {"tables": [{"source": "in.c-test.partners", "destination": "partners.csv"}]}},
        )
        assert isinstance(result, list)
        assert any(item.get("value") == "partners.csv" for item in result)

    def test_sync_load_field_mapping(self, odoo, kbc_datadir):
        """loadFieldMapping returns fuzzy-matched field mapping for res.partner."""
        write_input_csv(kbc_datadir, "partners.csv", [{"name": "test", "email": "x@x.com"}])
        result = self._run_sync_action(
            kbc_datadir,
            "loadFieldMapping",
            writer_params(odoo, self.PROTOCOL, "res.partner", "partners.csv"),
            storage={
                "input": {
                    "tables": [
                        {"source": "in.c-test.partners", "destination": "partners.csv", "columns": ["name", "email"]}
                    ]
                }
            },
        )
        assert result.get("type") == "data"
        mapping = result["data"]["field_mapping"]
        assert any(m["source_column"] == "name" and m["destination_field"] == "name" for m in mapping)
        assert any(m["source_column"] == "email" and m["destination_field"] == "email" for m in mapping)


class TestWriterJson2(TestWriterXmlRpc):
    """Runs the same tests with JSON-2 protocol."""

    PROTOCOL = "json2"
