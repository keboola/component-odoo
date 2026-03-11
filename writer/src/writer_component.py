"""
Odoo Writer Component

Writes CSV data into Odoo ERP via XML-RPC or JSON-2 API.
Reads an input table and creates new records in the configured Odoo model.
"""

import csv
import logging
from pathlib import Path
from typing import Any

from keboola.component.base import ComponentBase, sync_action
from keboola.component.exceptions import UserException
from keboola.component.sync_actions import SelectElement
from shared.connection import PROTOCOL_XMLRPC
from shared.odoo_base import OdooSyncActionsMixin, initialize_client
from writer_configuration import Configuration


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

    def run(self) -> None:
        """Main write logic."""
        self._validate_config()
        self._test_connection()

        input_path = Path(self.tables_in_path) / self.config.input_table
        if not input_path.exists():
            raise UserException(f"Input table not found: {self.config.input_table}")

        records = self._read_csv(input_path)

        if not records:
            logging.info("Input table is empty — nothing to write")
            return

        total_created = self._create_in_batches(records)
        logging.info(f"Successfully created {total_created} record(s) in {self.config.model}")

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
    def _read_csv(path: Path) -> list[dict[str, Any]]:
        """
        Read CSV and return records as dicts, stripping the 'id' column
        and omitting empty values so Odoo uses its field defaults.
        """
        records = []
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                record: dict[str, Any] = {}
                for key, value in row.items():
                    if key == "id":
                        continue
                    if value != "":
                        record[key] = value
                if record:
                    records.append(record)
        return records

    def _create_in_batches(self, records: list[dict[str, Any]]) -> int:
        """
        Send records to Odoo in batches.

        Args:
            records: All records to create

        Returns:
            Total number of records created

        Raises:
            UserException: If any batch fails
        """
        total = len(records)
        batch_size = self.config.batch_size
        total_created = 0

        for batch_num, start in enumerate(range(0, total, batch_size), start=1):
            batch = records[start : start + batch_size]
            logging.info(
                f"Creating batch {batch_num} ({len(batch)} records, {start + 1}–{start + len(batch)} of {total})"
            )

            try:
                created_ids = self.client.create(self.config.model, batch)
                total_created += len(created_ids)
            except UserException:
                raise
            except Exception as e:
                raise UserException(f"Batch {batch_num} failed (records {start + 1}–{start + len(batch)}): {e}")

        return total_created

    # === Sync Actions ===

    @sync_action("listInputTables")
    def list_input_tables_action(self) -> list[SelectElement]:
        """List input tables from the storage input mapping."""
        return [SelectElement(table.destination) for table in self.configuration.tables_input_mapping]


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
