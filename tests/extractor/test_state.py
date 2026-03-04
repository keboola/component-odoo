"""
Tests for state management: _validate_state(), incremental cursor, and state persistence.
"""

from unittest.mock import MagicMock

import pytest
from component import Component
from keboola.component.exceptions import UserException

from ..conftest import read_state, write_config, write_state


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.test_connection.return_value = None
    client.get_version.return_value = "16.0"
    client.get_model_fields.return_value = {"id": {"type": "integer", "string": "ID"}}
    client.search_read.return_value = []
    return client


@pytest.fixture
def run(kbc_datadir, mocker, mock_client):
    """Run Component with given config parameters; returns data_dir."""

    def _run(params: dict, client=mock_client):
        write_config(kbc_datadir, params)
        mocker.patch("component.Component._initialize_client", return_value=client)
        Component().run()
        return kbc_datadir

    return _run


BASE_PARAMS = {
    "odoo_url": "https://demo.odoo.com",
    "database": "demo",
    "username": "admin",
    "#api_key": "test123",
    "model": "res.partner",
}


class TestValidateState:
    def test_model_change_raises(self, kbc_datadir, mocker, mock_client):
        write_state(kbc_datadir, {"model": "sale.order", "domain": "", "last_id": 10})
        write_config(kbc_datadir, {**BASE_PARAMS, "model": "res.partner"})
        mocker.patch("component.Component._initialize_client", return_value=mock_client)

        with pytest.raises(UserException, match="Model changed"):
            Component().run()

    def test_domain_change_raises(self, kbc_datadir, mocker, mock_client):
        write_state(
            kbc_datadir,
            {
                "model": "res.partner",
                "domain": '[["is_company", "=", true]]',
                "last_id": 10,
            },
        )
        write_config(
            kbc_datadir,
            {
                **BASE_PARAMS,
                "domain": '[["is_company", "=", false]]',
            },
        )
        mocker.patch("component.Component._initialize_client", return_value=mock_client)

        with pytest.raises(UserException, match="Domain filter changed"):
            Component().run()

    def test_no_previous_state_succeeds(self, run):
        run(BASE_PARAMS)  # no state written — should not raise

    def test_matching_model_and_domain_succeeds(self, kbc_datadir, run):
        write_state(
            kbc_datadir,
            {
                "model": "res.partner",
                "domain": '[["is_company", "=", true]]',
                "last_id": 5,
            },
        )
        run({**BASE_PARAMS, "domain": '[["is_company", "=", true]]', "incremental": True})


class TestIncrementalCursor:
    def test_cursor_applied_to_domain_on_first_call(self, kbc_datadir, mocker, mock_client):
        write_state(kbc_datadir, {"model": "res.partner", "domain": "", "last_id": 5})
        write_config(kbc_datadir, {**BASE_PARAMS, "incremental": True})

        domains_seen = []

        def capture(*args, **kwargs):
            domains_seen.append(kwargs.get("domain", []))
            return []

        mock_client.search_read = capture
        mocker.patch("component.Component._initialize_client", return_value=mock_client)
        Component().run()

        id_filter = [d for d in domains_seen[0] if isinstance(d, tuple) and d[0] == "id"]
        assert id_filter == [("id", ">", 5)]

    def test_full_load_ignores_cursor_from_state(self, kbc_datadir, mocker, mock_client):
        write_state(kbc_datadir, {"model": "res.partner", "domain": "", "last_id": 100})
        write_config(kbc_datadir, {**BASE_PARAMS, "incremental": False})

        domains_seen = []

        def capture(*args, **kwargs):
            domains_seen.append(kwargs.get("domain", []))
            return [{"id": 1}] if len(domains_seen) == 1 else []

        mock_client.search_read = capture
        mocker.patch("component.Component._initialize_client", return_value=mock_client)
        Component().run()

        id_filters = [d for d in domains_seen[0] if isinstance(d, tuple) and d[0] == "id"]
        assert not id_filters


class TestStatePersistence:
    def test_last_id_saved_in_incremental_mode(self, kbc_datadir, mocker):
        write_config(kbc_datadir, {**BASE_PARAMS, "incremental": True})

        client = MagicMock()
        client.test_connection.return_value = None
        client.get_version.return_value = "16.0"
        client.get_model_fields.return_value = {"id": {"type": "integer", "string": "ID"}}
        client.search_read.return_value = [{"id": 50}]

        mocker.patch("component.Component._initialize_client", return_value=client)
        Component().run()

        assert read_state(kbc_datadir)["last_id"] == 50

    def test_last_id_is_zero_in_full_load(self, kbc_datadir, mocker):
        write_config(kbc_datadir, {**BASE_PARAMS, "incremental": False})

        client = MagicMock()
        client.test_connection.return_value = None
        client.get_version.return_value = "16.0"
        client.get_model_fields.return_value = {"id": {"type": "integer", "string": "ID"}}
        client.search_read.return_value = [{"id": 999}]

        mocker.patch("component.Component._initialize_client", return_value=client)
        Component().run()

        assert read_state(kbc_datadir)["last_id"] == 0
