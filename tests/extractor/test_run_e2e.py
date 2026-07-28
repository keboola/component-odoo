"""
End-to-end tests for Component.run().

Mocks only the Odoo API client; uses pytest's tmp_path and real CSV file verification.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from extractor_component import Component

from ..conftest import read_csv, read_state, write_config


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.test_connection.return_value = None
    client.get_version.return_value = "16.0"
    return client


@pytest.fixture
def run_component(kbc_datadir, mocker, mock_client):
    """Factory: write config, patch client, instantiate and run Component."""

    def _run(parameters: dict, client: MagicMock = mock_client) -> Path:
        write_config(kbc_datadir, parameters)
        mocker.patch("extractor_component.initialize_client", return_value=client)
        Component().run()
        return kbc_datadir

    return _run


BASE_PARAMS = {
    "odoo_url": "https://demo.odoo.com",
    "database": "demo",
    "username": "admin",
    "#api_key": "test123",
    "api_protocol": "xmlrpc",
    "model": "res.partner",
}


class TestFullExtraction:
    def test_scalar_fields_written_to_csv(self, run_component, mock_client):
        mock_client.get_model_fields.return_value = {
            "id": {"type": "integer", "string": "ID"},
            "name": {"type": "char", "string": "Name"},
            "email": {"type": "char", "string": "Email"},
        }
        mock_client.search_read.side_effect = [
            [
                {"id": 1, "name": "Partner 1", "email": "p1@example.com"},
                {"id": 2, "name": "Partner 2", "email": False},
            ],
            [{"id": 3, "name": "Partner 3", "email": "p3@example.com"}],
            [],
        ]

        data_dir = run_component({**BASE_PARAMS, "fields": ["id", "name", "email"], "page_size": 2})

        records = read_csv(data_dir, "res_partner")
        assert len(records) == 3
        assert records[0] == {"id": "1", "name": "Partner 1", "email": "p1@example.com"}
        assert records[1]["email"] == ""  # False -> None -> empty string in CSV
        assert records[2]["id"] == "3"

    def test_manifest_and_metadata_files_created(self, run_component, mock_client):
        mock_client.get_model_fields.return_value = {
            "id": {"type": "integer", "string": "ID"},
        }
        mock_client.search_read.return_value = [{"id": 1}]

        data_dir = run_component(BASE_PARAMS)

        tables = data_dir / "out" / "tables"
        assert (tables / "res_partner.csv.manifest").exists()
        assert any(tables.glob("metadata__*"))

    def test_state_written_after_full_load(self, run_component, mock_client):
        mock_client.get_model_fields.return_value = {"id": {"type": "integer", "string": "ID"}}
        mock_client.search_read.return_value = [{"id": 42}]

        data_dir = run_component(BASE_PARAMS)

        state = read_state(data_dir)
        assert state["model"] == "res.partner"
        assert state["last_write_date"] == ""  # not incremental
        assert state["last_run"]["records_fetched"] == 1


class TestRelationalFields:
    def test_many2one_flattened(self, run_component, mock_client):
        mock_client.get_model_fields.return_value = {
            "id": {"type": "integer", "string": "ID"},
            "country_id": {"type": "many2one", "string": "Country", "relation": "res.country"},
        }
        mock_client.search_read.return_value = [
            {"id": 1, "name": "Azure", "country_id": [233, "United States"]},
            {"id": 2, "name": "Deco", "country_id": [75, "France"]},
        ]

        data_dir = run_component(BASE_PARAMS)

        records = read_csv(data_dir, "res_partner")
        assert records[0]["country_id_id"] == "233"
        assert records[0]["country_id_name"] == "United States"
        assert records[1]["country_id_id"] == "75"

    def test_many2one_false_on_first_page_populated_on_second_produces_consistent_csv(self, run_component, mock_client):
        """Regression: False many2one on page 1 must not produce a bare column that mismatches page 2."""
        mock_client.get_model_fields.return_value = {
            "id": {"type": "integer", "string": "ID"},
            "name": {"type": "char", "string": "Name"},
            "picking_id": {"type": "many2one", "string": "Picking", "relation": "stock.picking"},
        }
        mock_client.search_read.side_effect = [
            [{"id": 1, "name": "Move A", "picking_id": False}],
            [{"id": 2, "name": "Move B", "picking_id": [42, "PICK/001"]}],
            [],
        ]

        data_dir = run_component({**BASE_PARAMS, "model": "stock.move", "page_size": 1})

        records = read_csv(data_dir, "stock_move")
        assert len(records) == 2
        assert set(records[0].keys()) == set(records[1].keys()), "Column sets differ between pages"
        assert records[0]["picking_id_id"] == ""
        assert records[0]["picking_id_name"] == ""
        assert records[1]["picking_id_id"] == "42"
        assert records[1]["picking_id_name"] == "PICK/001"

    def test_many2many_split_to_bridge_table(self, run_component, mock_client):
        mock_client.get_model_fields.return_value = {
            "id": {"type": "integer", "string": "ID"},
            "category_id": {"type": "many2many", "string": "Tags", "relation": "res.partner.category"},
        }
        mock_client.search_read.side_effect = [
            [
                {"id": 1, "name": "Partner 1", "category_id": [5, 9, 15]},
                {"id": 2, "name": "Partner 2", "category_id": []},
            ],
            [],
        ]

        data_dir = run_component(BASE_PARAMS)

        main = read_csv(data_dir, "res_partner")
        assert len(main) == 2
        assert "category_id" not in main[0]

        bridge = read_csv(data_dir, "res_partner__category_id")
        assert len(bridge) == 3
        assert bridge[0] == {"partner_id": "1", "category_id": "5"}
        assert bridge[1] == {"partner_id": "1", "category_id": "9"}
        assert bridge[2] == {"partner_id": "1", "category_id": "15"}


class TestIncrementalExtraction:
    def test_modified_record_re_extracted(self, kbc_datadir, mocker, mock_client):
        """Regression: a record modified after creation must be re-fetched despite its low id."""
        from ..conftest import write_state

        write_state(
            kbc_datadir,
            {
                "model": "stock.picking",
                "domain": "",
                "last_write_date": "2026-07-20 00:00:00",
                "last_run": {"timestamp": "2026-07-20T00:00:00+00:00", "records_fetched": 5},
            },
        )
        write_config(kbc_datadir, {**BASE_PARAMS, "model": "stock.picking", "incremental": True})

        domains_seen = []

        def capture_search_read(*args, **kwargs):
            domains_seen.append(list(kwargs.get("domain", [])))
            if len(domains_seen) > 1:
                return []
            return [{"id": 3, "name": "OLC-P/IN/03958", "state": "done", "write_date": "2026-07-23 08:33:48"}]

        mock_client.search_read = capture_search_read
        mock_client.get_model_fields.return_value = {
            "id": {"type": "integer", "string": "ID"},
            "state": {"type": "selection", "string": "Status"},
            "write_date": {"type": "datetime", "string": "Last Updated on"},
        }
        mocker.patch("extractor_component.initialize_client", return_value=mock_client)

        Component().run()

        assert domains_seen[0] == [("write_date", ">=", "2026-07-20 00:00:00")]
        records = read_csv(kbc_datadir, "stock_picking")
        assert records[0]["state"] == "done"
        assert read_state(kbc_datadir)["last_write_date"] == "2026-07-23 08:33:48"

    def test_write_date_persisted_in_state(self, run_component, mock_client):
        mock_client.get_model_fields.return_value = {
            "id": {"type": "integer", "string": "ID"},
            "write_date": {"type": "datetime", "string": "Last Updated on"},
        }
        mock_client.search_read.return_value = [{"id": 50, "write_date": "2026-07-23 08:33:48"}]

        data_dir = run_component({**BASE_PARAMS, "incremental": True})

        assert read_state(data_dir)["last_write_date"] == "2026-07-23 08:33:48"

    def test_domain_filter_passed_to_search_read(self, kbc_datadir, mocker, mock_client):
        write_config(kbc_datadir, {**BASE_PARAMS, "domain": '[["is_company", "=", true]]'})

        domains_seen = []

        def capture(*args, **kwargs):
            domains_seen.append(kwargs.get("domain", []))
            return [{"id": 1, "name": "Company A"}] if len(domains_seen) == 1 else []

        mock_client.search_read = capture
        mock_client.get_model_fields.return_value = {"id": {"type": "integer", "string": "ID"}}
        mocker.patch("extractor_component.initialize_client", return_value=mock_client)

        Component().run()

        assert ["is_company", "=", True] in domains_seen[0] or ("is_company", "=", True) in domains_seen[0]
