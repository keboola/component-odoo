"""
Tests for Component._split_records() and metadata generation.
"""

from typing import Any
from unittest.mock import MagicMock

from configuration import Configuration
from extractor_component import Component


class TestSplitRecords:
    def test_many2one_flattened_to_main_table(self):
        records: list[dict[str, Any]] = [{"id": 1, "name": "Test", "country_id": [21, "United States"]}]
        result = Component._split_records(records, "res.partner", "res_partner.csv")

        assert len(result.main_records) == 1
        assert result.main_records[0]["country_id_id"] == 21
        assert result.main_records[0]["country_id_name"] == "United States"
        assert not result.bridge_tables

    def test_many2many_split_to_bridge_table(self):
        records: list[dict[str, Any]] = [{"id": 1, "name": "Test", "tag_ids": [5, 9, 12]}]
        result = Component._split_records(records, "res.partner", "res_partner.csv")

        assert "tag_ids" not in result.main_records[0]
        bridge = result.bridge_tables["res_partner__tag_ids.csv"]
        assert bridge.primary_key == ["partner_id", "tag_id"]
        assert bridge.records == [
            {"partner_id": 1, "tag_id": 5},
            {"partner_id": 1, "tag_id": 9},
            {"partner_id": 1, "tag_id": 12},
        ]

    def test_false_converted_to_none(self):
        records: list[dict[str, Any]] = [{"id": 1, "email": False}]
        result = Component._split_records(records, "res.partner", "res_partner.csv")

        assert result.main_records[0]["email"] is None

    def test_empty_relationship_list_skipped(self):
        records: list[dict[str, Any]] = [{"id": 1, "tag_ids": []}]
        result = Component._split_records(records, "res.partner", "res_partner.csv")

        assert len(result.main_records) == 1
        assert not result.bridge_tables

    def test_multiple_relationships_produce_separate_tables(self):
        records: list[dict[str, Any]] = [{"id": 15, "name": "Azure", "category_id": [5], "child_ids": [27, 34, 28]}]
        result = Component._split_records(records, "res.partner", "res_partner.csv")

        assert result.main_records[0]["id"] == 15
        assert len(result.bridge_tables) == 2

        cat = result.bridge_tables["res_partner__category_id.csv"]
        assert cat.primary_key == ["partner_id", "category_id"]
        assert len(cat.records) == 1

        child = result.bridge_tables["res_partner__child_ids.csv"]
        assert child.primary_key == ["partner_id", "child_id"]
        assert len(child.records) == 3


class TestMetadataGeneration:
    def test_metadata_file_created_during_extraction(self, tmp_path, mocker):
        out_dir = tmp_path / "out" / "tables"
        out_dir.mkdir(parents=True)

        mock_client = MagicMock()
        mock_client.get_model_fields.return_value = {
            "id": {"type": "integer", "string": "ID"},
            "name": {"type": "char", "string": "Name"},
            "country_id": {"type": "many2one", "string": "Country", "relation": "res.country"},
            "category_id": {"type": "many2many", "string": "Tags", "relation": "res.partner.category"},
        }
        mock_client.search_read.return_value = [
            {"id": 1, "name": "Test", "country_id": [233, "United States"], "category_id": [5]}
        ]

        def make_table(name, **kwargs):
            t = MagicMock()
            t.full_path = str(out_dir / name)
            return t

        mocker.patch("extractor_component.Component.__init__", return_value=None)

        comp = Component()
        comp.client = mock_client
        comp.state = {}
        comp.create_out_table_definition = make_table
        comp.write_manifest = MagicMock()
        mocker.patch.object(
            type(comp),
            "tables_out_path",
            new_callable=lambda: property(lambda self: str(out_dir)),
        )
        comp.config = Configuration(
            odoo_url="https://demo.odoo.com",
            database="demo",
            username="admin",
            api_key="test123",
            model="res.partner",
            fields=["id", "name", "country_id", "category_id"],
        )

        comp._extract_with_paging()

        assert any(out_dir.glob("metadata__*"))
