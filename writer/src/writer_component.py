"""
Odoo Writer Component

Writes CSV data into Odoo ERP via XML-RPC or JSON-2 API.
Reads an input table and creates new records in the configured Odoo model.
"""

import csv
import logging
import re
from pathlib import Path
from typing import Any

from keboola.component.base import ComponentBase, sync_action
from keboola.component.exceptions import UserException
from keboola.component.sync_actions import SelectElement
from keboola.http_client import HttpClient
from shared.connection import PROTOCOL_XMLRPC
from shared.odoo_base import OdooSyncActionsMixin, initialize_client
from writer_configuration import Configuration, FieldMapping


class Component(OdooSyncActionsMixin, ComponentBase):
    """
    Odoo Writer Component.

    Reads an input CSV table and creates records in the configured Odoo model.
    Follows clean orchestrator pattern with delegated methods.
    """

    def __init__(self) -> None:
        """Initialize component."""
        super().__init__()
        self.config = Configuration(**self.configuration.parameters)
        self.client = initialize_client(self.config)
        env = self.environment_variables
        self._storage_api_token: str = env.token
        self._storage_api_url: str = env.url or ""

    def run(self) -> None:
        """Main write logic."""
        self._validate_config()
        self._test_connection()

        input_path = Path(self.tables_in_path) / self.config.input_table
        if not input_path.exists():
            raise UserException(f"Input table not found: {self.config.input_table}")

        records = self._read_csv(input_path, self.config.field_mapping)

        if not records:
            logging.info("Input table is empty — nothing to write")
            return

        total_created, failed_records = self._create_in_batches(records)
        logging.info(f"Successfully created {total_created} record(s) in {self.config.model}")

        if failed_records:
            self._write_failed_records(failed_records)
            logging.warning(f"{len(failed_records)} record(s) failed and written to failed_records.csv")

    def _validate_config(self) -> None:
        """Validate configuration before writing."""
        errors = []

        if not self.config.database:
            errors.append("Database name is required")
        if not self.config.api_key:
            errors.append("API key is required")
        if self.config.api_protocol == PROTOCOL_XMLRPC and not self.config.username:
            errors.append("Username is required for XML-RPC")
        if not self.config.model:
            errors.append("Model name is required")
        if not self.config.input_table:
            errors.append("Input table is required")
        if self.config.batch_size < 1:
            errors.append("Batch size must be at least 1")

        if errors:
            raise UserException(f"Configuration incomplete: {'; '.join(errors)}")

    def _test_connection(self) -> None:
        """Test Odoo connection and authentication."""
        logging.info("Testing Odoo connection...")
        self.client.test_connection()

    @staticmethod
    def _read_csv(path: Path, field_mapping: list[FieldMapping]) -> list[dict[str, Any]]:
        """
        Read CSV and return records as dicts.

        If field_mapping is configured, renames source columns to destination fields
        and drops unmapped columns. Empty values are omitted so Odoo uses field defaults.

        If no field_mapping is configured, passes all non-empty columns through as-is,
        stripping the 'id' column.
        """
        mapping = {fm.source_column: fm.destination_field for fm in field_mapping if fm.source_column}

        records = []
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                record: dict[str, Any] = {}
                if mapping:
                    for src, dst in mapping.items():
                        value = row.get(src, "")
                        if value != "" and dst:
                            record[dst] = value
                else:
                    for key, value in row.items():
                        if key == "id":
                            continue
                        if value != "":
                            record[key] = value
                if record:
                    records.append(record)
        return records

    def _create_in_batches(self, records: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
        """
        Send records to Odoo in batches.

        If continue_on_error is True, failed batches are collected and returned.
        If continue_on_error is False, raises on the first batch failure.

        Returns:
            Tuple of (total_created, failed_records)
        """
        total = len(records)
        batch_size = self.config.batch_size
        total_created = 0
        failed_records: list[dict[str, Any]] = []

        for batch_num, start in enumerate(range(0, total, batch_size), start=1):
            batch = records[start : start + batch_size]
            logging.info(
                f"Creating batch {batch_num} ({len(batch)} records, {start + 1}–{start + len(batch)} of {total})"
            )

            try:
                created_ids = self.client.create(self.config.model, batch)
                total_created += len(created_ids)
            except UserException as e:
                if self.config.continue_on_error:
                    logging.warning(f"Batch {batch_num} failed (records {start + 1}–{start + len(batch)}): {e}")
                    failed_records.extend(batch)
                else:
                    raise
            except Exception as e:
                if self.config.continue_on_error:
                    logging.warning(f"Batch {batch_num} failed (records {start + 1}–{start + len(batch)}): {e}")
                    failed_records.extend(batch)
                else:
                    raise UserException(f"Batch {batch_num} failed (records {start + 1}–{start + len(batch)}): {e}")

        return total_created, failed_records

    def _write_failed_records(self, failed_records: list[dict[str, Any]]) -> None:
        """Write failed records to output table for inspection."""
        table = self.create_out_table_definition(name="failed_records.csv", incremental=False)
        fieldnames = list(failed_records[0].keys())
        with open(table.full_path, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(failed_records)
        self.write_manifest(table)

    # === Sync Actions ===

    @sync_action("listInputTables")
    def list_input_tables_action(self) -> list[SelectElement]:
        """List input tables from the storage input mapping."""
        return [SelectElement(table.destination) for table in self.configuration.tables_input_mapping]

    @sync_action("loadFieldMapping")
    def load_field_mapping_action(self) -> dict[str, Any]:
        """
        Auto-generate field mapping by fuzzy-matching input table columns to Odoo model fields.

        Uses the configured input table mapping to get columns (explicit column list from
        the mapping config, or falls back to Storage API). Preserves any existing manually
        customized destination_field values.

        Returns pre-populated field_mapping[] array plus _metadata_ with all Odoo fields
        for the destination dropdown.
        """
        model = self.config.model
        table_name = self.config.input_table

        if not model:
            raise UserException("Please select a model first")
        if not table_name:
            raise UserException("Please select an input table first")

        input_mappings = self.configuration.tables_input_mapping
        table_mapping = next((t for t in input_mappings if t.destination == table_name), None)
        if not table_mapping:
            raise UserException(
                f"Input table '{table_name}' not found in input mapping. "
                "Please add the table to the input mapping first."
            )

        columns = (
            list(table_mapping.columns)
            if table_mapping.columns
            else self._get_table_columns_from_sapi(table_mapping.source)
        )

        if not columns:
            raise UserException(
                f"Could not determine columns for input table '{table_name}'. "
                "Please ensure the table exists in Keboola Storage."
            )

        odoo_fields = self.client.get_model_fields(model)
        odoo_field_names = [f for f in odoo_fields.keys() if f != "_unknown"]

        existing = {fm.source_column: fm.destination_field for fm in self.config.field_mapping if fm.source_column}

        field_mapping = []
        for col in columns:
            if col in existing:
                destination = existing[col]
            else:
                destination = self._fuzzy_match_columns([col], odoo_field_names)[0]["destination_field"]
            field_mapping.append({"source_column": col, "destination_field": destination})

        return {
            "type": "data",
            "data": {
                **self.configuration.parameters,
                "field_mapping": field_mapping,
                "_metadata_": {"api_fields": [{"field_name": f, "label": f} for f in sorted(odoo_field_names)]},
            },
        }

    def _get_table_columns_from_sapi(self, table_id: str) -> list[str]:
        """Fetch table columns from Keboola Storage API by table ID."""
        if not self._storage_api_token or not self._storage_api_url:
            logging.warning("Storage API not available, skipping columns check for %s", table_id)
            return []
        try:
            client = HttpClient(base_url=self._storage_api_url.rstrip("/") + "/v2/storage")
            response = client.get(
                endpoint_path=f"tables/{table_id}",
                headers={"X-StorageApi-Token": self._storage_api_token},
            )
            return response.get("columns", [])
        except Exception as e:
            logging.warning("Could not fetch columns for %s: %s", table_id, e)
            return []

    @staticmethod
    def _fuzzy_match_columns(csv_columns: list[str], api_fields: list[str]) -> list[dict[str, str]]:
        """
        Fuzzy-match CSV column names to Odoo field names.

        Priority:
          1. Exact match
          2. Case-insensitive match
          3. Normalized match (strip _, -, spaces, dots; lowercase)

        Unmatched columns get an empty destination_field.
        """

        def normalize(s: str) -> str:
            return re.sub(r"[_\-\s.]", "", s).lower()

        api_lower = {f.lower(): f for f in api_fields}
        api_normalized = {normalize(f): f for f in api_fields}

        mapping: list[dict[str, str]] = []
        for col in csv_columns:
            dest = ""
            if col in api_fields:
                dest = col
            elif col.lower() in api_lower:
                dest = api_lower[col.lower()]
            elif normalize(col) in api_normalized:
                dest = api_normalized[normalize(col)]
            mapping.append({"source_column": col, "destination_field": dest})
        return mapping


if __name__ == "__main__":
    try:
        comp = Component()
        comp.execute_action()
    except UserException as exc:
        logging.exception(exc)
        exit(1)
    except Exception as exc:
        logging.exception(exc)
        exit(2)
