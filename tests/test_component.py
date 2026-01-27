"""
Tests for Odoo Extractor Component.

Uses modern Python 3.9+ type hints and proper mocking.
"""

import unittest
from typing import Any
from unittest.mock import MagicMock, Mock, patch

from clients.xmlrpc_client import XmlRpcClient
from component import Component
from configuration import Configuration


class TestConfiguration(unittest.TestCase):
    """Test configuration validation."""

    def test_valid_config(self) -> None:
        """Test valid configuration."""
        config = Configuration(
            odoo_url="https://demo.odoo.com",
            database="demo",
            username="admin",
            api_key="test123",
            model="res.partner",
        )
        self.assertEqual(config.odoo_url, "https://demo.odoo.com")
        self.assertEqual(config.model, "res.partner")
        self.assertEqual(config.table_name, "res_partner.csv")

    def test_url_validation_invalid(self) -> None:
        """Test URL validation rejects invalid URLs."""
        with self.assertRaises(Exception):
            Configuration(
                odoo_url="invalid-url",
                database="demo",
                username="admin",
                api_key="test",
                model="res.partner",
            )

    def test_trailing_slash_removed(self) -> None:
        """Test trailing slash is removed from URL."""
        config = Configuration(
            odoo_url="https://demo.odoo.com/",
            database="demo",
            username="admin",
            api_key="test",
            model="res.partner",
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

    def test_split_records_many2one(self) -> None:
        """Test many2one fields are flattened in main table."""
        records: list[dict[str, Any]] = [
            {
                "id": 1,
                "name": "Test",
                "country_id": [21, "United States"],
            }
        ]

        result = Component._split_records(records, "res.partner", "res_partner.csv")

        self.assertEqual(len(result.main_records), 1)
        self.assertEqual(result.main_records[0]["id"], 1)
        self.assertEqual(result.main_records[0]["country_id_id"], 21)
        self.assertEqual(result.main_records[0]["country_id_name"], "United States")
        self.assertEqual(len(result.bridge_tables), 0)  # No relationship tables for many2one

    def test_split_records_many2many(self) -> None:
        """Test many2many fields are split into relationship tables."""
        records: list[dict[str, Any]] = [{"id": 1, "name": "Test", "tag_ids": [5, 9, 12]}]

        result = Component._split_records(records, "res.partner", "res_partner.csv")

        # Main table should not have tag_ids
        self.assertEqual(len(result.main_records), 1)
        self.assertEqual(result.main_records[0]["id"], 1)
        self.assertEqual(result.main_records[0]["name"], "Test")
        self.assertNotIn("tag_ids", result.main_records[0])

        # Relationship table should have 3 records
        self.assertIn("res_partner__tag_ids.csv", result.bridge_tables)
        rel_metadata = result.bridge_tables
        rel_data = rel_metadata["res_partner__tag_ids.csv"]
        self.assertEqual(rel_data.primary_key, ["partner_id", "tag_id"])
        self.assertEqual(rel_data.table_name, "res_partner__tag_ids.csv")
        self.assertEqual(len(rel_data.records), 3)
        self.assertEqual(rel_data.records[0], {"partner_id": 1, "tag_id": 5})
        self.assertEqual(rel_data.records[1], {"partner_id": 1, "tag_id": 9})
        self.assertEqual(rel_data.records[2], {"partner_id": 1, "tag_id": 12})

    def test_split_records_false_values(self) -> None:
        """Test False values converted to None."""
        records: list[dict[str, Any]] = [{"id": 1, "email": False}]

        result = Component._split_records(records, "res.partner", "res_partner.csv")

        self.assertEqual(len(result.main_records), 1)
        self.assertIsNone(result.main_records[0]["email"])
        self.assertEqual(len(result.bridge_tables), 0)

    def test_split_records_empty_relationships(self) -> None:
        """Test empty relationship lists don't create tables."""
        records: list[dict[str, Any]] = [{"id": 1, "tag_ids": []}]

        result = Component._split_records(records, "res.partner", "res_partner.csv")

        self.assertEqual(len(result.main_records), 1)
        self.assertEqual(len(result.bridge_tables), 0)  # No tables for empty lists

    def test_split_records_multiple_relationships(self) -> None:
        """Test multiple relationship fields create separate tables."""
        records: list[dict[str, Any]] = [
            {
                "id": 15,
                "name": "Azure",
                "category_id": [5],
                "child_ids": [27, 34, 28],
            }
        ]

        result = Component._split_records(records, "res.partner", "res_partner.csv")

        # Main table
        self.assertEqual(len(result.main_records), 1)
        self.assertEqual(result.main_records[0]["id"], 15)

        # Two relationship tables
        self.assertEqual(len(result.bridge_tables), 2)
        self.assertIn("res_partner__category_id.csv", result.bridge_tables)
        self.assertIn("res_partner__child_ids.csv", result.bridge_tables)
        rel_metadata = result.bridge_tables

        # category_id has 1 record and correct primary key
        category_data = rel_metadata["res_partner__category_id.csv"]
        self.assertEqual(category_data.primary_key, ["partner_id", "category_id"])
        self.assertEqual(category_data.table_name, "res_partner__category_id.csv")
        self.assertEqual(len(category_data.records), 1)

        # child_ids has 3 records and correct primary key
        child_data = rel_metadata["res_partner__child_ids.csv"]
        self.assertEqual(child_data.primary_key, ["partner_id", "child_id"])
        self.assertEqual(child_data.table_name, "res_partner__child_ids.csv")
        self.assertEqual(len(child_data.records), 3)


class TestMetadataGeneration(unittest.TestCase):
    """Test metadata file generation."""

    @patch("builtins.open", new_callable=lambda: MagicMock())
    @patch("component.Component._write_csv")
    @patch("component.Component.write_manifest")
    @patch("component.Component.create_out_table_definition")
    def test_metadata_file_created(
        self,
        mock_table_def: Mock,
        mock_manifest: Mock,
        mock_write_csv: Mock,
        mock_open: Mock,
    ) -> None:
        """Test that metadata file is created during extraction."""
        # Mock the client's field metadata
        mock_client = MagicMock()
        mock_client.get_model_fields.return_value = {
            "id": {"type": "integer", "string": "ID"},
            "name": {"type": "char", "string": "Name"},
            "country_id": {
                "type": "many2one",
                "string": "Country",
                "relation": "res.country",
            },
            "category_id": {
                "type": "many2many",
                "string": "Tags",
                "relation": "res.partner.category",
            },
        }
        mock_client.search_read.return_value = [
            {
                "id": 1,
                "name": "Test Partner",
                "country_id": [233, "United States"],
                "category_id": [5],
            }
        ]

        # Create component with mocked client
        with patch("component.Component._initialize_client", return_value=mock_client):
            with patch("component.Component.__init__") as mock_init:
                mock_init.return_value = None
                comp = Component()
                comp.client = mock_client
                comp.state = {}

            # Mock the tables_out_path property
            with patch.object(
                type(comp),
                "tables_out_path",
                new_callable=lambda: property(lambda self: "/tmp/test_out"),
            ):
                # Mock table definition - return different paths for different tables
                def create_mock_table(name, **kwargs):
                    mock_table = MagicMock()
                    mock_table.full_path = f"/tmp/test_out/{name}.csv"
                    return mock_table

                mock_table_def.side_effect = create_mock_table

                # Set config
                comp.config = Configuration(
                    odoo_url="https://demo.odoo.com",
                    database="demo",
                    username="admin",
                    api_key="test123",
                    model="res.partner",
                    fields=["id", "name", "country_id", "category_id"],
                )

                # Run extraction
                comp._extract_with_paging()

                # Verify metadata file was opened for writing
                metadata_calls = [call for call in mock_open.call_args_list if "metadata__" in str(call)]
                self.assertTrue(len(metadata_calls) > 0, "Metadata file should be created")


if __name__ == "__main__":
    unittest.main()
