"""
Tests for the Odoo Writer Component.

Mocks only the Odoo API client; uses real CSV files via pytest tmp_path.
"""

import csv
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest
from writer_component import Component

from ..conftest import write_config

BASE_PARAMS = {
    "odoo_url": "https://demo.odoo.com",
    "database": "demo",
    "username": "admin",
    "#api_key": "test123",
    "api_protocol": "xmlrpc",
    "model": "res.partner",
    "input_table": "partners.csv",
}


def write_input_csv(data_dir: Path, filename: str, rows: list[dict]) -> Path:
    """Write an input CSV table into data_dir/in/tables/."""
    tables_dir = data_dir / "in" / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    path = tables_dir / filename
    if rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        path.write_text("")
    return path


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.test_connection.return_value = {"version": "16.0", "protocol": "XML-RPC"}
    client.create.return_value = [1]
    return client


@pytest.fixture
def run_component(kbc_datadir, mocker, mock_client):
    """Factory: write config + input CSV, patch client, instantiate and run Component."""

    def _run(parameters: dict, rows: list[dict], client: MagicMock = mock_client) -> Path:
        write_config(kbc_datadir, parameters)
        write_input_csv(kbc_datadir, parameters["input_table"], rows)
        mocker.patch("writer_component.Component._initialize_client", return_value=client)
        Component().run()
        return kbc_datadir

    return _run


class TestBasicWrite:
    def test_records_created_from_csv(self, run_component, mock_client):
        rows = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"},
        ]
        run_component(BASE_PARAMS, rows)

        mock_client.create.assert_called_once_with(
            "res.partner",
            [
                {"name": "Alice", "email": "alice@example.com"},
                {"name": "Bob", "email": "bob@example.com"},
            ],
        )

    def test_id_column_stripped(self, run_component, mock_client):
        rows = [{"id": "42", "name": "Alice", "email": "alice@example.com"}]
        run_component(BASE_PARAMS, rows)

        sent = mock_client.create.call_args[0][1]
        assert all("id" not in record for record in sent)
        assert sent[0] == {"name": "Alice", "email": "alice@example.com"}

    def test_empty_values_omitted(self, run_component, mock_client):
        rows = [{"name": "Alice", "email": "", "phone": "123"}]
        run_component(BASE_PARAMS, rows)

        sent = mock_client.create.call_args[0][1]
        assert sent[0] == {"name": "Alice", "phone": "123"}
        assert "email" not in sent[0]

    def test_empty_csv_no_api_calls(self, run_component, mock_client):
        run_component(BASE_PARAMS, [])
        mock_client.create.assert_not_called()

    def test_row_with_only_id_and_empty_values_skipped(self, run_component, mock_client):
        rows = [{"id": "1", "name": "", "email": ""}]
        run_component(BASE_PARAMS, rows)
        mock_client.create.assert_not_called()


class TestBatching:
    def test_batching_splits_correctly(self, run_component, mock_client):
        rows = [{"name": f"Partner {i}"} for i in range(250)]
        mock_client.create.return_value = list(range(100))

        run_component({**BASE_PARAMS, "batch_size": 100}, rows)

        assert mock_client.create.call_count == 3
        # First two batches: 100 records each
        assert len(mock_client.create.call_args_list[0][0][1]) == 100
        assert len(mock_client.create.call_args_list[1][0][1]) == 100
        # Last batch: remaining 50
        assert len(mock_client.create.call_args_list[2][0][1]) == 50

    def test_single_batch_when_records_fit(self, run_component, mock_client):
        rows = [{"name": f"Partner {i}"} for i in range(10)]
        run_component({**BASE_PARAMS, "batch_size": 100}, rows)

        mock_client.create.assert_called_once()
        assert len(mock_client.create.call_args[0][1]) == 10

    def test_batch_size_one(self, run_component, mock_client):
        rows = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
        mock_client.create.return_value = [1]

        run_component({**BASE_PARAMS, "batch_size": 1}, rows)

        assert mock_client.create.call_count == 3
        assert mock_client.create.call_args_list == [
            call("res.partner", [{"name": "A"}]),
            call("res.partner", [{"name": "B"}]),
            call("res.partner", [{"name": "C"}]),
        ]


class TestErrorHandling:
    def test_missing_input_table_raises(self, kbc_datadir, mocker, mock_client):
        write_config(kbc_datadir, BASE_PARAMS)
        # Do NOT write the input CSV
        mocker.patch("writer_component.Component._initialize_client", return_value=mock_client)

        from keboola.component.exceptions import UserException

        with pytest.raises(UserException, match="Input table not found"):
            Component().run()

    def test_batch_failure_raises_user_exception(self, run_component, mock_client):
        from keboola.component.exceptions import UserException

        mock_client.create.side_effect = Exception("Odoo internal error")
        rows = [{"name": "Alice"}]

        with pytest.raises(UserException, match="Batch 1 failed"):
            run_component(BASE_PARAMS, rows)

    def test_user_exception_from_client_propagated(self, run_component, mock_client):
        from keboola.component.exceptions import UserException

        mock_client.create.side_effect = UserException("Invalid field: foo")
        rows = [{"foo": "bar"}]

        with pytest.raises(UserException, match="Invalid field: foo"):
            run_component(BASE_PARAMS, rows)


class TestConnectionCheck:
    def test_connection_tested_on_run(self, run_component, mock_client):
        rows = [{"name": "Alice"}]
        run_component(BASE_PARAMS, rows)
        mock_client.test_connection.assert_called_once()
