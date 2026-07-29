"""
Tests for state management: _validate_state(), incremental cursor, and state persistence.
"""

from unittest.mock import MagicMock

import pytest
from extractor_component import Component
from keboola.component.exceptions import UserException

from ..conftest import read_state, write_config, write_state


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.test_connection.return_value = None
    client.get_version.return_value = "16.0"
    client.get_model_fields.return_value = MODEL_FIELDS
    client.search_read.return_value = []
    return client


@pytest.fixture
def run(kbc_datadir, mocker, mock_client):
    """Run Component with given config parameters; returns data_dir."""

    def _run(params: dict, client=mock_client):
        write_config(kbc_datadir, params)
        mocker.patch("extractor_component.initialize_client", return_value=client)
        Component().run()
        return kbc_datadir

    return _run


MODEL_FIELDS = {
    "id": {"type": "integer", "string": "ID"},
    "write_date": {"type": "datetime", "string": "Last Updated on"},
}

BASE_PARAMS = {
    "odoo_url": "https://demo.odoo.com",
    "database": "demo",
    "username": "admin",
    "#api_key": "test123",
    "model": "res.partner",
}


class TestValidateState:
    def test_model_change_raises(self, kbc_datadir, mocker, mock_client):
        write_state(kbc_datadir, {"model": "sale.order", "domain": "", "last_write_date": "2026-01-01 00:00:00"})
        write_config(kbc_datadir, {**BASE_PARAMS, "model": "res.partner"})
        mocker.patch("extractor_component.initialize_client", return_value=mock_client)

        with pytest.raises(UserException, match="Model changed"):
            Component().run()

    def test_domain_change_raises(self, kbc_datadir, mocker, mock_client):
        write_state(
            kbc_datadir,
            {
                "model": "res.partner",
                "domain": '[["is_company", "=", true]]',
                "last_write_date": "2026-01-01 00:00:00",
            },
        )
        write_config(
            kbc_datadir,
            {
                **BASE_PARAMS,
                "domain": '[["is_company", "=", false]]',
            },
        )
        mocker.patch("extractor_component.initialize_client", return_value=mock_client)

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
                "last_write_date": "2026-01-01 00:00:00",
            },
        )
        run({**BASE_PARAMS, "domain": '[["is_company", "=", true]]', "incremental": True})


def capture_domains(mock_client, mocker, pages=None):
    """Record the domain of every search_read call; return the recorded domains."""
    domains_seen: list[list] = []
    pages = pages or []

    def capture(*args, **kwargs):
        domains_seen.append(kwargs.get("domain", []))
        return pages[len(domains_seen) - 1] if len(domains_seen) <= len(pages) else []

    mock_client.search_read = capture
    mocker.patch("extractor_component.initialize_client", return_value=mock_client)
    return domains_seen


class TestIncrementalCursor:
    def test_write_date_cursor_applied_to_domain(self, kbc_datadir, mocker, mock_client):
        write_state(
            kbc_datadir,
            {"model": "res.partner", "domain": "", "last_write_date": "2026-07-23 08:33:48"},
        )
        write_config(kbc_datadir, {**BASE_PARAMS, "incremental": True})

        domains_seen = capture_domains(mock_client, mocker)
        Component().run()

        assert domains_seen[0] == [("write_date", ">=", "2026-07-23 08:33:48")]

    def test_no_id_cursor_carried_over_between_runs(self, kbc_datadir, mocker, mock_client):
        """Modified records keep their original id, so the id cursor must reset each run."""
        write_state(
            kbc_datadir,
            {"model": "res.partner", "domain": "", "last_write_date": "2026-07-23 08:33:48"},
        )
        write_config(kbc_datadir, {**BASE_PARAMS, "incremental": True})

        domains_seen = capture_domains(mock_client, mocker)
        Component().run()

        id_filters = [d for d in domains_seen[0] if isinstance(d, tuple) and d[0] == "id"]
        assert not id_filters

    def test_legacy_id_state_triggers_full_sweep(self, kbc_datadir, mocker, mock_client):
        write_state(kbc_datadir, {"model": "res.partner", "domain": "", "last_id": 100})
        write_config(kbc_datadir, {**BASE_PARAMS, "incremental": True})

        domains_seen = capture_domains(mock_client, mocker)
        Component().run()

        assert domains_seen[0] == []

    def test_full_load_ignores_cursor_from_state(self, kbc_datadir, mocker, mock_client):
        write_state(
            kbc_datadir,
            {"model": "res.partner", "domain": "", "last_write_date": "2026-07-23 08:33:48"},
        )
        write_config(kbc_datadir, {**BASE_PARAMS, "incremental": False})

        domains_seen = capture_domains(mock_client, mocker, pages=[[{"id": 1}]])
        Component().run()

        assert domains_seen[0] == []

    def test_user_domain_preserved_across_pages(self, kbc_datadir, mocker, mock_client):
        write_config(
            kbc_datadir,
            {**BASE_PARAMS, "domain": '[["id", ">", 10]]', "page_size": 2},
        )

        pages = [[{"id": 11}, {"id": 12}], [{"id": 13}]]
        domains_seen = capture_domains(mock_client, mocker, pages=pages)
        Component().run()

        assert domains_seen[0] == [["id", ">", 10]]
        assert domains_seen[1] == [["id", ">", 10], ("id", ">", 12)]

    def test_model_without_write_date_resumes_by_id(self, kbc_datadir, mocker, mock_client):
        """Models lacking write_date keep classic id-based incremental instead of re-sweeping everything."""
        mock_client.get_model_fields.return_value = {"id": {"type": "integer", "string": "ID"}}
        write_state(kbc_datadir, {"model": "res.partner", "domain": "", "last_id": 100})
        write_config(kbc_datadir, {**BASE_PARAMS, "incremental": True})

        domains_seen = capture_domains(mock_client, mocker)
        Component().run()

        assert domains_seen[0] == [("id", ">", 100)]

    def test_model_without_write_date_first_run_has_no_cursor(self, kbc_datadir, mocker, mock_client):
        """First incremental run of a write_date-less model has no id cursor yet (initial full load)."""
        mock_client.get_model_fields.return_value = {"id": {"type": "integer", "string": "ID"}}
        write_config(kbc_datadir, {**BASE_PARAMS, "incremental": True})

        domains_seen = capture_domains(mock_client, mocker)
        Component().run()

        assert domains_seen[0] == []


class TestWriteDateField:
    def test_write_date_added_to_selected_fields_and_stripped_from_output(self, kbc_datadir, mocker, mock_client):
        write_config(
            kbc_datadir,
            {**BASE_PARAMS, "incremental": True, "fields": ["id", "name"]},
        )

        fields_seen = []

        def capture(*args, **kwargs):
            fields_seen.append(kwargs.get("fields"))
            if len(fields_seen) > 1:
                return []
            return [{"id": 1, "name": "Azure", "write_date": "2026-07-23 08:33:48"}]

        mock_client.search_read = capture
        mocker.patch("extractor_component.initialize_client", return_value=mock_client)
        Component().run()

        assert fields_seen[0] == ["id", "name", "write_date"]
        header = (kbc_datadir / "out" / "tables" / "res_partner.csv").read_text().splitlines()[0]
        assert "write_date" not in header

    def test_full_load_with_selected_fields_does_not_fetch_or_leak_write_date(self, kbc_datadir, mocker, mock_client):
        """Full load must not add write_date to the request or the output, even on a model that has it."""
        write_config(
            kbc_datadir,
            {**BASE_PARAMS, "incremental": False, "fields": ["id", "name"]},
        )

        fields_seen = []

        def capture(*args, **kwargs):
            fields_seen.append(kwargs.get("fields"))
            if len(fields_seen) > 1:
                return []
            return [{"id": 1, "name": "Azure"}]

        mock_client.search_read = capture
        mocker.patch("extractor_component.initialize_client", return_value=mock_client)
        Component().run()

        assert fields_seen[0] == ["id", "name"]
        header = (kbc_datadir / "out" / "tables" / "res_partner.csv").read_text().splitlines()[0]
        assert "write_date" not in header


class TestStatePersistence:
    def test_highest_write_date_saved_in_incremental_mode(self, kbc_datadir, mocker, mock_client):
        write_config(kbc_datadir, {**BASE_PARAMS, "incremental": True})
        mock_client.search_read.return_value = [
            {"id": 50, "write_date": "2026-07-23 08:33:48"},
            {"id": 51, "write_date": "2026-07-21 10:00:00"},
        ]

        mocker.patch("extractor_component.initialize_client", return_value=mock_client)
        Component().run()

        assert read_state(kbc_datadir)["last_write_date"] == "2026-07-23 08:33:48"

    def test_cursor_kept_when_nothing_changed(self, kbc_datadir, mocker, mock_client):
        write_state(
            kbc_datadir,
            {"model": "res.partner", "domain": "", "last_write_date": "2026-07-23 08:33:48"},
        )
        write_config(kbc_datadir, {**BASE_PARAMS, "incremental": True})

        mocker.patch("extractor_component.initialize_client", return_value=mock_client)
        Component().run()

        assert read_state(kbc_datadir)["last_write_date"] == "2026-07-23 08:33:48"

    def test_cursor_is_empty_in_full_load(self, kbc_datadir, mocker, mock_client):
        write_config(kbc_datadir, {**BASE_PARAMS, "incremental": False})
        mock_client.search_read.return_value = [{"id": 999, "write_date": "2026-07-23 08:33:48"}]

        mocker.patch("extractor_component.initialize_client", return_value=mock_client)
        Component().run()

        assert read_state(kbc_datadir)["last_write_date"] == ""

    def test_id_cursor_saved_for_model_without_write_date(self, kbc_datadir, mocker, mock_client):
        """Write_date-less incremental persists the highest id as the resume cursor."""
        mock_client.get_model_fields.return_value = {"id": {"type": "integer", "string": "ID"}}
        write_config(kbc_datadir, {**BASE_PARAMS, "incremental": True})
        mock_client.search_read.return_value = [{"id": 50}, {"id": 51}]

        mocker.patch("extractor_component.initialize_client", return_value=mock_client)
        Component().run()

        state = read_state(kbc_datadir)
        assert state["last_id"] == 51
        assert state["last_write_date"] == ""
