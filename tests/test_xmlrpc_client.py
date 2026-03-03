"""
Tests for XmlRpcClient — all methods with mocked xmlrpc.client.ServerProxy.
"""

import xmlrpc.client
from unittest.mock import MagicMock

import pytest
from keboola.component.exceptions import UserException

from shared.clients.xmlrpc_client import XmlRpcClient

URL = "https://demo.odoo.com"
DATABASE = "demo"
USERNAME = "admin"
API_KEY = "test_api_key"


@pytest.fixture
def mock_proxy(mocker):
    """Patch ServerProxy globally; return a mock instance used for all proxies."""
    mock_instance = MagicMock()
    mocker.patch("shared.clients.xmlrpc_client.xmlrpc.client.ServerProxy", return_value=mock_instance)
    return mock_instance


@pytest.fixture
def client(mock_proxy):
    c = XmlRpcClient(url=URL, database=DATABASE, username=USERNAME, api_key=API_KEY)
    c.common = mock_proxy
    c.models = mock_proxy
    c.db = mock_proxy
    return c


@pytest.fixture
def authed_client(client, mock_proxy):
    """Client with uid already set — skips authenticate() in tested methods."""
    client.uid = 123
    return client


class TestAuthentication:
    def test_success_returns_uid(self, client, mock_proxy):
        mock_proxy.authenticate.return_value = 123
        assert client.authenticate() == 123

    def test_false_response_raises(self, client, mock_proxy):
        mock_proxy.authenticate.return_value = False
        with pytest.raises(UserException, match="Authentication failed"):
            client.authenticate()

    def test_xmlrpc_fault_raises(self, client, mock_proxy):
        mock_proxy.authenticate.side_effect = xmlrpc.client.Fault(1, "Invalid credentials")
        with pytest.raises(UserException, match="Invalid credentials"):
            client.authenticate()


class TestSearchRead:
    def test_returns_records(self, authed_client, mock_proxy):
        mock_proxy.execute_kw.return_value = [
            {"id": 1, "name": "Test Partner"},
            {"id": 2, "name": "Another"},
        ]
        records = authed_client.search_read(
            model="res.partner",
            domain=[("is_company", "=", True)],
            fields=["id", "name"],
            limit=10,
            order="name asc",
        )

        assert len(records) == 2
        args = mock_proxy.execute_kw.call_args[0]
        assert args[3] == "res.partner"
        assert args[4] == "search_read"
        assert args[5] == [[("is_company", "=", True)]]
        assert args[6]["limit"] == 10
        assert args[6]["order"] == "name asc"

    def test_auto_authenticates_when_uid_not_set(self, client, mock_proxy):
        mock_proxy.authenticate.return_value = 456
        mock_proxy.execute_kw.return_value = [{"id": 1}]

        client.uid = None
        client.search_read(model="res.partner")

        mock_proxy.authenticate.assert_called_once()

    def test_xmlrpc_fault_raises(self, authed_client, mock_proxy):
        mock_proxy.execute_kw.side_effect = xmlrpc.client.Fault(1, "Access denied")
        with pytest.raises(UserException, match="Access denied"):
            authed_client.search_read(model="res.partner")


class TestGetModelFields:
    def test_returns_field_definitions(self, authed_client, mock_proxy):
        mock_proxy.execute_kw.return_value = {
            "id": {"type": "integer", "string": "ID"},
            "name": {"type": "char", "string": "Name", "required": True},
            "partner_id": {"type": "many2one", "string": "Partner", "relation": "res.partner"},
        }
        fields = authed_client.get_model_fields("sale.order")

        assert fields["name"]["required"] is True
        assert fields["partner_id"]["relation"] == "res.partner"
        assert mock_proxy.execute_kw.call_args[0][4] == "fields_get"


class TestListModels:
    def test_returns_models_and_filters_transient(self, authed_client, mock_proxy):
        mock_proxy.execute_kw.return_value = [
            {"model": "res.partner", "name": "Contact"},
            {"model": "sale.order", "name": "Sales Order"},
        ]
        models = authed_client.list_models()

        assert len(models) == 2
        domain = mock_proxy.execute_kw.call_args[0][5][0]
        assert ("transient", "=", False) in domain
        assert ("model", "!=", "_unknown") in domain


class TestGetVersion:
    def test_returns_version_string(self, client, mock_proxy):
        mock_proxy.version.return_value = {"server_version": "16.0"}
        assert client.get_version() == "16.0"

    def test_does_not_require_authentication(self, client, mock_proxy):
        mock_proxy.version.return_value = {"server_version": "17.0"}
        client.uid = None
        client.get_version()
        mock_proxy.authenticate.assert_not_called()


class TestTestConnection:
    def test_success_returns_version_and_protocol(self, client, mock_proxy):
        mock_proxy.version.return_value = {"server_version": "18.0"}
        mock_proxy.authenticate.return_value = 789

        result = client.test_connection()

        assert result["version"] == "18.0"
        assert result["protocol"] == "XML-RPC"

    @pytest.mark.parametrize(
        "database,username,api_key,expected_msg",
        [
            ("", USERNAME, API_KEY, "Database name is required"),
            (DATABASE, None, API_KEY, "Username is required"),
            (DATABASE, USERNAME, "", "API key is required"),
        ],
    )
    def test_missing_credential_raises(self, mock_proxy, database, username, api_key, expected_msg):
        c = XmlRpcClient(url=URL, database=database, username=username, api_key=api_key)
        with pytest.raises(UserException, match=expected_msg):
            c.test_connection()


class TestListDatabases:
    def test_returns_database_list(self, client, mock_proxy):
        mock_proxy.list.return_value = ["production", "staging", "test"]
        assert client.list_databases() == ["production", "staging", "test"]

    def test_xmlrpc_fault_raises(self, client, mock_proxy):
        mock_proxy.list.side_effect = xmlrpc.client.Fault(1, "Access Denied")
        with pytest.raises(UserException, match="Access Denied"):
            client.list_databases()
