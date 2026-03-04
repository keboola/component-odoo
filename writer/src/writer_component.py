"""
Odoo Writer Component

Writes CSV data into Odoo ERP via XML-RPC or JSON-2 API.
Reads an input table and creates new records in the configured Odoo model.
"""

import csv
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from keboola.component.base import ComponentBase, sync_action
from keboola.component.exceptions import UserException
from keboola.component.sync_actions import SelectElement
from shared.clients.json2_client import Json2Client
from shared.clients.xmlrpc_client import XmlRpcClient
from writer_configuration import Configuration

PROTOCOL_JSON2 = "json2"
PROTOCOL_XMLRPC = "xmlrpc"
DISPLAY_JSON2 = "JSON-2"
DISPLAY_XMLRPC = "XML-RPC"


class Component(ComponentBase):
    """
    Odoo Writer Component.

    Reads an input CSV table and creates records in the configured Odoo model.
    Follows clean orchestrator pattern with delegated methods.
    """

    def __init__(self) -> None:
        """Initialize component."""
        super().__init__()
        self.config = Configuration(**self.configuration.parameters)
        self.client = self._initialize_client(self.config)

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

    def _initialize_client(self, config: Configuration) -> XmlRpcClient | Json2Client:
        """Initialize and return appropriate Odoo client based on api_protocol config."""
        ClientClass = Json2Client if config.api_protocol == PROTOCOL_JSON2 else XmlRpcClient
        return ClientClass(
            url=config.odoo_url,
            database=config.database,
            username=config.username,
            api_key=config.api_key,
        )

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

    @sync_action("testConnection")
    def test_connection_action(self) -> dict[str, str]:
        """Test connection to Odoo and return version + protocol info."""
        try:
            odoo_url = self.config.odoo_url
            database = self.config.database
            username = self.config.username
            api_key = self.config.api_key
            selected_protocol = self.config.api_protocol

            xmlrpc_client = XmlRpcClient(odoo_url, database, username, api_key)
            json2_client = Json2Client(odoo_url, database, username, api_key)

            protocols_available = {}
            odoo_version = None

            try:
                odoo_version = xmlrpc_client.get_version()
                protocols_available[DISPLAY_XMLRPC] = True
            except Exception as e:
                protocols_available[DISPLAY_XMLRPC] = False
                logging.debug(f"XML-RPC availability check failed: {e}")

            try:
                version = json2_client.get_version()
                protocols_available[DISPLAY_JSON2] = True
                if not odoo_version:
                    odoo_version = version
            except Exception as e:
                protocols_available[DISPLAY_JSON2] = False
                logging.debug(f"JSON-2 availability check failed: {e}")

            if not odoo_version:
                raise UserException("Cannot connect to Odoo instance at this URL")

            supports_parts = []
            for protocol in [DISPLAY_JSON2, DISPLAY_XMLRPC]:
                symbol = "✓" if protocols_available.get(protocol, False) else "✗"
                supports_parts.append(f"{protocol} {symbol}")
            supports_str = ", ".join(supports_parts)

            selected_client: XmlRpcClient | Json2Client | None = None
            auth_message = ""

            if selected_protocol == PROTOCOL_JSON2:
                if not protocols_available[DISPLAY_JSON2]:
                    return {
                        "status": "error",
                        "message": (
                            f"Odoo {odoo_version}. Supports: {supports_str}. "
                            f"{DISPLAY_JSON2} not available on this instance"
                        ),
                    }
                try:
                    json2_client.test_connection()
                    selected_client = json2_client
                    auth_message = f"Authenticated using {DISPLAY_JSON2}"
                except Exception as e:
                    return {
                        "status": "error",
                        "message": (
                            f"Odoo {odoo_version}. Supports: {supports_str}. "
                            f"Authentication failed using {DISPLAY_JSON2} ({e})"
                        ),
                    }
            else:
                if not protocols_available[DISPLAY_XMLRPC]:
                    return {
                        "status": "error",
                        "message": (
                            f"Odoo {odoo_version}. Supports: {supports_str}. "
                            f"{DISPLAY_XMLRPC} not available on this instance"
                        ),
                    }
                try:
                    xmlrpc_client.test_connection()
                    selected_client = xmlrpc_client
                    auth_message = f"Authenticated using {DISPLAY_XMLRPC}"
                except Exception as e:
                    return {
                        "status": "error",
                        "message": (
                            f"Odoo {odoo_version}. Supports: {supports_str}. "
                            f"Authentication failed using {DISPLAY_XMLRPC} ({e})"
                        ),
                    }

            model_suffix = ""
            try:
                models = selected_client.list_models()
                model_suffix = f", {len(models)} models"
            except Exception as e:
                logging.warning(f"Could not fetch model count: {e}")

            return {
                "status": "success",
                "message": f"Odoo {odoo_version}. Supports: {supports_str}. {auth_message}{model_suffix}",
            }

        except UserException:
            raise
        except Exception as e:
            raise UserException(f"Connection test failed: {str(e)}")

    @sync_action("listModels")
    def list_models_action(self) -> list[SelectElement]:
        """List available Odoo models for the model dropdown."""
        try:
            models = self.client.list_models()
            return [
                SelectElement(value=m["model"], label=f"{m['model']} - {m['name']}")
                for m in sorted(models, key=lambda m: m["model"])
            ]
        except UserException:
            raise
        except Exception as e:
            raise UserException(f"Failed to load models: {str(e)}")

    @sync_action("listFields")
    def list_fields_action(self) -> list[SelectElement]:
        """List fields for the selected model — helps user know expected column names."""
        try:
            model = self.config.model
            if not model:
                raise UserException("Please select a model first")

            fields_dict = self.client.get_model_fields(model)
            return [
                SelectElement(
                    value=field_name,
                    label=f"{info.get('string', field_name)} ({field_name}) - {info.get('type', 'unknown')}",
                )
                for field_name, info in fields_dict.items()
                if field_name != "_unknown"
            ]
        except UserException:
            raise
        except Exception as e:
            raise UserException(f"Failed to load fields: {str(e)}")

    @sync_action("listInputTables")
    def list_input_tables_action(self) -> list[SelectElement]:
        """List input tables from the storage input mapping."""
        return [SelectElement(table.destination) for table in self.configuration.tables_input_mapping]

    @sync_action("listDatabases")
    def list_databases_action(self) -> list[SelectElement]:
        """
        List available databases on the Odoo instance.

        For odoo.com instances, database listing is blocked for security.
        This method detects odoo.com and suggests the database name from the URL.

        Returns:
            Dropdown data with database names

        Raises:
            UserException: If listing databases fails
        """
        try:
            odoo_url = self.config.odoo_url
            is_odoo_com = ".odoo.com" in odoo_url.lower()

            if is_odoo_com:
                parsed = urlparse(odoo_url)
                hostname = parsed.hostname or ""
                subdomain = hostname.replace(".odoo.com", "").replace(".dev", "").replace(".saas", "")

                if subdomain:
                    logging.info(f"Detected odoo.com instance - suggesting database name from subdomain: {subdomain}")
                    return [SelectElement(value=subdomain)]
                else:
                    raise UserException(
                        "This is an Odoo.com instance. Database listing is blocked for security. "
                        "Please enter the database name manually (usually matches your subdomain)."
                    )

            if self.config.api_protocol == PROTOCOL_JSON2:
                client = Json2Client(odoo_url, "", None, "")
                databases = client.list_databases()
            else:
                client = XmlRpcClient(odoo_url, "", "", "")
                databases = client.list_databases()

            logging.info(f"Found {len(databases)} database(s): {databases}")

            dropdown_data = [SelectElement(value=db) for db in databases]
            return dropdown_data

        except UserException as e:
            if "Access Denied" in str(e) and ".odoo.com" in self.config.odoo_url.lower():
                raise UserException(
                    "Database listing is blocked on Odoo.com instances. "
                    "Please enter the database name manually (it usually matches your subdomain)."
                )
            raise e
        except Exception as e:
            raise UserException(f"Failed to list databases: {str(e)}")


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
