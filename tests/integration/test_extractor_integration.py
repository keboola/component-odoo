"""
Integration tests for the Odoo extractor against a live local Odoo instance.

Run with:
    pytest tests/integration/test_extractor_integration.py -v

Requires docker-compose.test.yml to be running (handled by the `odoo` fixture).
Tests run against both XML-RPC and JSON-2 protocols.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from extractor_component import Component

from .conftest import OdooConfig, read_csv, read_state, write_config

pytestmark = pytest.mark.timeout(60)


def base_params(odoo: OdooConfig, protocol: str) -> dict[str, Any]:
    return {
        "odoo_url": odoo.odoo_url,
        "database": odoo.database,
        "username": odoo.username,
        "#api_key": odoo.api_key,
        "api_protocol": protocol,
        "model": "res.partner",
        "fields": ["id", "name", "email", "is_company", "city"],
        "incremental": False,
    }


def run_extractor(kbc_datadir: Path, params: dict) -> Path:
    write_config(kbc_datadir, params)
    Component().run()
    return kbc_datadir


class TestExtractorXmlRpc:
    PROTOCOL = "xmlrpc"

    def test_extracts_res_partner_with_demo_data(self, odoo, kbc_datadir):
        """Demo data includes ~30+ partners — verify we get records back."""
        run_extractor(kbc_datadir, base_params(odoo, self.PROTOCOL))

        rows = read_csv(kbc_datadir, "res_partner")
        assert len(rows) > 10
        # All rows have required columns
        assert all("id" in r and "name" in r for r in rows)

    def test_field_selection(self, odoo, kbc_datadir):
        """Only requested fields appear in output."""
        params = {**base_params(odoo, self.PROTOCOL), "fields": ["id", "name"]}
        run_extractor(kbc_datadir, params)

        rows = read_csv(kbc_datadir, "res_partner")
        assert len(rows) > 0
        assert all(set(r.keys()) == {"id", "name"} for r in rows)

    def test_domain_filter_reduces_results(self, odoo, kbc_datadir):
        """Domain filter returns fewer records than unfiltered."""
        # First extract all
        run_extractor(kbc_datadir, base_params(odoo, self.PROTOCOL))
        all_rows = read_csv(kbc_datadir, "res_partner")

        # Then extract only companies
        params = {**base_params(odoo, self.PROTOCOL), "domain": '[["is_company", "=", true]]'}
        run_extractor(kbc_datadir, params)
        company_rows = read_csv(kbc_datadir, "res_partner")

        assert len(company_rows) < len(all_rows)
        assert all(r["is_company"] == "True" for r in company_rows)

    def test_many2one_field_produces_two_columns(self, odoo, kbc_datadir):
        """country_id (many2one) → country_id_id + country_id_name columns alongside original."""
        params = {**base_params(odoo, self.PROTOCOL), "fields": ["id", "name", "country_id"]}
        run_extractor(kbc_datadir, params)

        rows = read_csv(kbc_datadir, "res_partner")
        # Find a row that actually has a country set
        rows_with_country = [r for r in rows if r.get("country_id_id")]
        assert len(rows_with_country) > 0
        r = rows_with_country[0]
        assert "country_id_id" in r
        assert "country_id_name" in r

    def test_incremental_saves_state_and_resumes(self, odoo, kbc_datadir):
        """Incremental mode saves last_id in state; re-run with state returns no new rows."""
        params = {**base_params(odoo, self.PROTOCOL), "incremental": True}

        # First run — full extract
        run_extractor(kbc_datadir, params)
        state = read_state(kbc_datadir)
        assert "last_id" in state
        assert int(state["last_id"]) > 0

        # Second run with same state — should return only records with id > last_id
        # (Other tests may have created new records in Odoo, so we just verify the cursor is used)
        import shutil

        (kbc_datadir / "in" / "state.json").parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(kbc_datadir / "out" / "state.json", kbc_datadir / "in" / "state.json")
        last_id = int(state["last_id"])
        # Remove first run's output so we can tell if second run writes anything
        csv_path = kbc_datadir / "out" / "tables" / "res_partner.csv"
        csv_path.unlink(missing_ok=True)
        run_extractor(kbc_datadir, params)

        # If second run wrote nothing (no new records), CSV won't exist — that's fine
        # If it wrote something, all IDs must be > last_id (cursor was used correctly)
        if csv_path.exists():
            second_rows = read_csv(kbc_datadir, "res_partner")
            assert all(int(r["id"]) > last_id for r in second_rows)
        # Either way: the state was used (logs confirm "resuming from ID {last_id}")

    def test_metadata_table_written(self, odoo, kbc_datadir):
        """Metadata table is written alongside main table."""
        run_extractor(kbc_datadir, base_params(odoo, self.PROTOCOL))

        meta_rows = read_csv(kbc_datadir, "metadata__res_partner")
        assert len(meta_rows) > 0
        assert all("field_name" in r and "field_type" in r for r in meta_rows)

    def _run_sync_action(self, kbc_datadir: Path, action: str, params: dict) -> Any:
        """Run a sync action and return the parsed JSON result."""
        import io
        import sys

        (kbc_datadir / "config.json").write_text(json.dumps({"action": action, "parameters": params}))
        captured = io.StringIO()
        sys.stdout = captured
        try:
            Component().execute_action()
        finally:
            sys.stdout = sys.__stdout__
        # Component logs may prefix the JSON — find the last JSON line
        for line in reversed(captured.getvalue().splitlines()):
            line = line.strip()
            if line.startswith("{") or line.startswith("["):
                return json.loads(line)
        raise AssertionError(f"No JSON found in output: {captured.getvalue()!r}")

    def test_sync_test_connection(self, odoo, kbc_datadir):
        """testConnection sync action returns version info."""
        result = self._run_sync_action(kbc_datadir, "testConnection", base_params(odoo, self.PROTOCOL))
        assert result.get("status") == "success"

    def test_sync_list_databases(self, odoo, kbc_datadir):
        """listDatabases returns at least the test database."""
        result = self._run_sync_action(kbc_datadir, "listDatabases", base_params(odoo, self.PROTOCOL))
        db_names = [item.get("value") or item.get("label") for item in result]
        assert odoo.database in db_names

    def test_sync_list_models(self, odoo, kbc_datadir):
        """listModels returns res.partner in the list."""
        result = self._run_sync_action(kbc_datadir, "listModels", base_params(odoo, self.PROTOCOL))
        model_values = [item.get("value") for item in result]
        assert "res.partner" in model_values

    def test_sync_list_fields(self, odoo, kbc_datadir):
        """listFields returns fields for res.partner."""
        params = {**base_params(odoo, self.PROTOCOL), "model": "res.partner"}
        result = self._run_sync_action(kbc_datadir, "listFields", params)
        field_values = [item.get("value") for item in result]
        assert "name" in field_values
        assert "email" in field_values


class TestExtractorJson2(TestExtractorXmlRpc):
    """Runs the same tests with JSON-2 protocol."""

    PROTOCOL = "json2"
