"""
Tests for Json2Client — all methods with mocked HttpClient.
"""

from unittest.mock import MagicMock

import pytest
from keboola.component.exceptions import UserException

from shared.clients.json2_client import Json2Client

URL = "https://demo.odoo.com"
DATABASE = "demo"
API_KEY = "test_api_key_123"


@pytest.fixture
def mock_http(mocker):
    """Patch HttpClient and return the mock instance."""
    mock_instance = MagicMock()
    mocker.patch("shared.clients.json2_client.HttpClient", return_value=mock_instance)
    return mock_instance


@pytest.fixture
def client(mock_http):
    return Json2Client(url=URL, database=DATABASE, username=None, api_key=API_KEY)


class TestInitialization:
    def test_http_client_configured_correctly(self, mocker):
        mock_class = mocker.patch("shared.clients.json2_client.HttpClient")
        Json2Client(url=URL, database=DATABASE, username=None, api_key=API_KEY)

        call_kwargs = mock_class.call_args.kwargs
        assert call_kwargs["base_url"] == f"{URL}/json/2"
        assert call_kwargs["auth_header"]["Authorization"] == f"bearer {API_KEY}"
        assert call_kwargs["default_http_header"]["X-Odoo-Database"] == DATABASE


class TestGetVersion:
    def test_returns_version_string(self, client, mock_http):
        mock_http.get.return_value = {"version": "19.0"}
        assert client.get_version() == "19.0"

    def test_404_raises_user_exception(self, client, mock_http):
        err = Exception("not found")
        err.response = MagicMock(status_code=404)
        mock_http.get.side_effect = err

        with pytest.raises(UserException, match="404"):
            client.get_version()


class TestTestConnection:
    def test_success_returns_version_and_protocol(self, client, mock_http):
        mock_http.get.return_value = {"version": "19.0"}
        mock_http.post.return_value = [{"id": 1}]

        result = client.test_connection()

        assert result["version"] == "19.0"
        assert result["protocol"] == "JSON-2"

    def test_empty_api_key_raises(self, mock_http):
        c = Json2Client(url=URL, database=DATABASE, username=None, api_key="")
        with pytest.raises(UserException, match="API key is required"):
            c.test_connection()

    def test_401_raises_with_invalid_api_key_message(self, client, mock_http):
        mock_http.get.return_value = {"version": "19.0"}
        err = Exception("unauthorized")
        err.response = MagicMock(status_code=401)
        mock_http.post.side_effect = err

        with pytest.raises(UserException, match="401"):
            client.test_connection()


class TestSearchRead:
    def test_returns_records(self, client, mock_http):
        mock_http.post.return_value = [
            {"id": 1, "name": "Partner 1"},
            {"id": 2, "name": "Partner 2"},
        ]
        records = client.search_read(
            model="res.partner",
            domain=[("is_company", "=", True)],
            fields=["id", "name"],
            limit=10,
            order="name asc",
        )

        assert len(records) == 2
        assert records[0]["name"] == "Partner 1"

        payload = mock_http.post.call_args.kwargs["json"]
        assert payload["domain"] == [("is_company", "=", True)]
        assert payload["fields"] == ["id", "name"]
        assert payload["limit"] == 10
        assert payload["order"] == "name asc"

    def test_empty_result(self, client, mock_http):
        mock_http.post.return_value = []
        assert client.search_read(model="res.partner") == []

    def test_404_includes_model_name_in_error(self, client, mock_http):
        err = Exception("not found")
        err.response = MagicMock(status_code=404)
        mock_http.post.side_effect = err

        with pytest.raises(UserException, match="nonexistent.model"):
            client.search_read(model="nonexistent.model")


class TestGetModelFields:
    def test_returns_field_definitions(self, client, mock_http):
        mock_http.post.return_value = {
            "id": {"type": "integer", "string": "ID"},
            "name": {"type": "char", "string": "Name"},
            "country_id": {"type": "many2one", "string": "Country", "relation": "res.country"},
        }
        fields = client.get_model_fields("res.partner")

        assert fields["name"]["type"] == "char"
        assert fields["country_id"]["relation"] == "res.country"
        assert mock_http.post.call_args.kwargs["endpoint_path"] == "res.partner/fields_get"


class TestListModels:
    def test_returns_model_list(self, client, mock_http):
        mock_http.post.return_value = [
            {"model": "res.partner", "name": "Contact"},
            {"model": "sale.order", "name": "Sales Order"},
        ]
        models = client.list_models()

        assert len(models) == 2
        assert models[0]["model"] == "res.partner"

        domain = mock_http.post.call_args.kwargs["json"]["domain"]
        assert ("transient", "=", False) in domain
        assert ("model", "!=", "_unknown") in domain


class TestListDatabases:
    def test_returns_database_list(self, client, mock_http):
        mock_http.post.return_value = {"result": ["db1", "db2", "db3"]}
        databases = client.list_databases()

        assert databases == ["db1", "db2", "db3"]
        assert mock_http.post.call_args.kwargs["is_absolute_path"] is True

    def test_unexpected_response_format_raises(self, client, mock_http):
        mock_http.post.return_value = {"error": "something went wrong"}
        with pytest.raises(UserException, match="Unexpected response format"):
            client.list_databases()
