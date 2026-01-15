"""
Tests for Odoo Extractor Component.

Uses modern Python 3.9+ type hints and proper mocking.
"""

import unittest
from typing import Any
from unittest.mock import MagicMock, Mock, patch

from clients.xmlrpc_client import XmlRpcClient
from component import Component
from configuration import Configuration, OdooEndpoint


class TestConfiguration(unittest.TestCase):
    """Test configuration validation."""

    def test_valid_config(self) -> None:
        """Test valid configuration."""
        config = Configuration(
            odoo_url="https://demo.odoo.com",
            database="demo",
            username="admin",
            api_key="test123",
            endpoints=[OdooEndpoint(model="res.partner", output_table="partners.csv")],
        )
        self.assertEqual(config.odoo_url, "https://demo.odoo.com")
        self.assertEqual(len(config.endpoints), 1)

    def test_url_validation_invalid(self) -> None:
        """Test URL validation rejects invalid URLs."""
        with self.assertRaises(Exception):
            Configuration(
                odoo_url="invalid-url",
                database="demo",
                username="admin",
                api_key="test",
                endpoints=[OdooEndpoint(model="test", output_table="test.csv")],
            )

    def test_trailing_slash_removed(self) -> None:
        """Test trailing slash is removed from URL."""
        config = Configuration(
            odoo_url="https://demo.odoo.com/",
            database="demo",
            username="admin",
            api_key="test",
            endpoints=[OdooEndpoint(model="test", output_table="test.csv")],
        )
        self.assertEqual(config.odoo_url, "https://demo.odoo.com")


class TestXmlRpcClient(unittest.TestCase):
    """Test Odoo client."""

    @patch("clients.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_authentication_success(self, mock_server: Mock) -> None:
        """Test successful authentication."""
        mock_common = MagicMock()
        mock_common.authenticate.return_value = 123
        mock_server.return_value = mock_common

        client = XmlRpcClient(
            url="https://demo.odoo.com",
            database="demo",
            username="admin",
            api_key="test",
        )
        client.common = mock_common

        uid = client.authenticate()
        self.assertEqual(uid, 123)

    @patch("clients.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_search_read(self, mock_server: Mock) -> None:
        """Test search_read method."""
        mock_models = MagicMock()
        mock_models.execute_kw.return_value = [{"id": 1, "name": "Test Partner"}]

        client = XmlRpcClient(
            url="https://demo.odoo.com",
            database="demo",
            username="admin",
            api_key="test",
        )
        client.models = mock_models
        client.uid = 123

        records = client.search_read(model="res.partner", fields=["id", "name"])

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "Test Partner")


class TestComponent(unittest.TestCase):
    """Test component logic."""

    def test_flatten_record_many2one(self) -> None:
        """Test flattening many2one fields."""
        record: dict[str, Any] = {
            "id": 1,
            "name": "Test",
            "country_id": [21, "United States"],
        }

        flattened = Component._flatten_record(record)

        self.assertEqual(flattened["id"], 1)
        self.assertEqual(flattened["country_id_id"], 21)
        self.assertEqual(flattened["country_id_name"], "United States")

    def test_flatten_record_many2many(self) -> None:
        """Test flattening many2many fields."""
        record: dict[str, Any] = {"id": 1, "tag_ids": [1, 5, 9]}

        flattened = Component._flatten_record(record)

        self.assertEqual(flattened["tag_ids"], "1,5,9")

    def test_flatten_record_false_values(self) -> None:
        """Test False values converted to None."""
        record: dict[str, Any] = {"id": 1, "email": False}

        flattened = Component._flatten_record(record)

        self.assertIsNone(flattened["email"])

    def test_flatten_record_normal_list(self) -> None:
        """Test normal lists are comma-separated."""
        record: dict[str, Any] = {"id": 1, "ids": [10, 20, 30]}

        flattened = Component._flatten_record(record)

        self.assertEqual(flattened["ids"], "10,20,30")


if __name__ == "__main__":
    unittest.main()
