"""
Odoo Extractor Component

Extracts data from Odoo ERP via XML-RPC API.
Uses modern Python 3.9+ type hints and clean orchestrator pattern.
"""

import csv
import logging
from pathlib import Path
from typing import Any

from keboola.component.base import ComponentBase, sync_action
from keboola.component.exceptions import UserException

from configuration import Configuration, OdooEndpoint
from odoo_client import OdooClient


class Component(ComponentBase):
    """
    Odoo Extractor Component.

    Connects to Odoo via XML-RPC and extracts data from configured models.
    Follows clean orchestrator pattern with delegated methods.
    """

    def __init__(self) -> None:
        """Initialize component."""
        super().__init__()
        self.client: OdooClient | None = None
        self.state: dict[str, Any] = {}

    def run(self) -> None:
        """
        Main extraction logic - clean orchestrator.

        Orchestrates the extraction workflow by delegating to well-named methods.
        Keeps this method concise (~20-30 lines) for readability.
        """
        params = self._validate_and_get_configuration()
        self.client = self._initialize_client(params)
        self._test_connection()

        # Load state once at the start
        self.state = self.get_state_file()

        for endpoint in params.endpoints:
            self._extract_endpoint(endpoint)

        # Write state once at the end
        if self.state:
            self.write_state_file(self.state)

        logging.info("Extraction completed successfully")

    def _validate_and_get_configuration(self) -> Configuration:
        """
        Validate and return parsed configuration.

        Returns:
            Validated configuration object

        Raises:
            UserException: If configuration is invalid
        """
        return Configuration(**self.configuration.parameters)

    def _initialize_client(self, params: Configuration) -> OdooClient:
        """
        Initialize and return Odoo client.

        Args:
            params: Configuration object

        Returns:
            Initialized OdooClient
        """
        return OdooClient(
            url=params.odoo_url,
            database=params.database,
            username=params.username,
            api_key=params.api_key,
        )

    def _test_connection(self) -> None:
        """Test Odoo connection and authentication."""
        if self.client:
            logging.info("Testing Odoo connection...")
            self.client.test_connection()

    def _extract_endpoint(self, endpoint: OdooEndpoint) -> None:
        """
        Extract data from a single Odoo model endpoint.

        Args:
            endpoint: Endpoint configuration
        """
        logging.info(f"Extracting {endpoint.model} -> {endpoint.output_table}")

        # Get state for incremental loading (use shared self.state)
        # Use nested structure: state["endpoints"][table_name]["last_id"]
        if not endpoint.incremental:
            last_id = 0
        else:
            endpoints_state = self.state.get("endpoints", {})
            endpoint_state = endpoints_state.get(endpoint.output_table, {})
            last_id = endpoint_state.get("last_id", 0)

        # Build domain filter
        domain = endpoint.domain or []
        if endpoint.incremental and last_id:
            domain.append(("id", ">", last_id))
            logging.info(f"Incremental load: fetching records with id > {last_id}")

        # Fetch data from Odoo
        if not self.client:
            raise UserException("Odoo client not initialized")

        records = self.client.search_read(
            model=endpoint.model,
            domain=domain,
            fields=endpoint.fields,
            limit=endpoint.limit,
            order=endpoint.order or "id asc",
        )

        if not records:
            logging.warning(f"No records found for {endpoint.model}")
            return

        # Create output table
        table = self.create_out_table_definition(
            name=endpoint.output_table,
            incremental=endpoint.incremental,
            primary_key=endpoint.primary_key or ["id"],
        )

        # Flatten and write data
        flattened_records = [self._flatten_record(record) for record in records]
        self._write_csv(Path(table.full_path), flattened_records)

        # Save manifest
        self.write_manifest(table)

        # Update state for incremental loading
        if endpoint.incremental and records:
            max_id = max(
                record.get("id", 0)
                for record in records
                if isinstance(record.get("id"), int)
            )

            # Update nested state structure in shared self.state
            if "endpoints" not in self.state:
                self.state["endpoints"] = {}
            if endpoint.output_table not in self.state["endpoints"]:
                self.state["endpoints"][endpoint.output_table] = {}

            self.state["endpoints"][endpoint.output_table]["last_id"] = max_id
            # Note: State is written once at the end of run(), not here
            logging.info(f"Updated state: last_id = {max_id}")

        logging.info(f"Wrote {len(records)} records to {endpoint.output_table}")

    @staticmethod
    def _flatten_record(record: dict[str, Any]) -> dict[str, Any]:
        """
        Flatten nested Odoo record structures.

        Odoo returns many2one fields as [id, name] tuples.
        This converts them to separate columns.

        Args:
            record: Raw Odoo record

        Returns:
            Flattened record dictionary
        """
        flattened: dict[str, Any] = {}

        for key, value in record.items():
            if (
                isinstance(value, (list, tuple))
                and len(value) == 2
                and isinstance(value[0], int)
            ):
                # Many2one field: [id, name]
                flattened[f"{key}_id"] = value[0]
                flattened[f"{key}_name"] = value[1]
            elif isinstance(value, list):
                # Many2many or one2many: list of IDs
                flattened[key] = ",".join(str(v) for v in value)
            elif value is False:
                # Odoo uses False for null values
                flattened[key] = None
            else:
                flattened[key] = value

        return flattened

    @staticmethod
    def _write_csv(file_path: Path, records: list[dict[str, Any]]) -> None:
        """
        Write records to CSV file.

        Args:
            file_path: Output CSV file path
            records: List of records to write
        """
        if not records:
            return

        # Get all unique keys from all records
        all_keys: set[str] = set()
        for record in records:
            all_keys.update(record.keys())

        fieldnames = sorted(all_keys)

        # Write CSV
        with open(file_path, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)

    @sync_action("testConnection")
    def test_connection_action(self) -> dict[str, str]:
        """
        Test Odoo connection - sync action for UI button.

        Returns:
            Success/error response for UI
        """
        try:
            # Get parameters (no full validation needed for sync actions)
            params = self.configuration.parameters
            odoo_url = params.get("odoo_url")
            database = params.get("database")
            username = params.get("username")
            api_key = params.get("#api_key")

            if not all([odoo_url, database, username, api_key]):
                raise UserException(
                    "All connection fields are required: Odoo URL, Database, Username, and API Key"
                )

            # Initialize client and test
            client = OdooClient(
                url=odoo_url,
                database=database,
                username=username,
                api_key=api_key,
            )
            client.test_connection()

            return {
                "status": "success",
                "message": "Connection successful! Odoo instance is accessible.",
            }

        except UserException as e:
            raise e
        except Exception as e:
            raise UserException(f"Connection test failed: {str(e)}")

    @sync_action("listModels")
    def list_models_action(self) -> dict[str, Any]:
        """
        List available Odoo models - sync action for model dropdown.

        Returns:
            Dropdown data with model names
        """
        try:
            # Get connection parameters
            params = self.configuration.parameters
            odoo_url = params.get("odoo_url")
            database = params.get("database")
            username = params.get("username")
            api_key = params.get("#api_key")

            if not all([odoo_url, database, username, api_key]):
                raise UserException("Connection credentials required to load models")

            # Initialize client and fetch models
            client = OdooClient(
                url=odoo_url,
                database=database,
                username=username,
                api_key=api_key,
            )
            models = client.list_models()

            # Format for Keboola dropdown: [{"value": "...", "label": "..."}]
            dropdown_data = [
                {
                    "value": model["model"],
                    "label": f"{model['name']} ({model['model']})",
                }
                for model in models
            ]

            return {"status": "success", "data": dropdown_data}

        except UserException as e:
            raise e
        except Exception as e:
            raise UserException(f"Failed to load models: {str(e)}")

    @sync_action("listFields")
    def list_fields_action(self) -> dict[str, Any]:
        """
        List fields for selected model - sync action for fields dropdown.
        Receives current form values including selected model.

        Returns:
            Dropdown data with field names
        """
        try:
            # Get connection parameters
            params = self.configuration.parameters
            odoo_url = params.get("odoo_url")
            database = params.get("database")
            username = params.get("username")
            api_key = params.get("#api_key")

            if not all([odoo_url, database, username, api_key]):
                raise UserException("Connection credentials required to load fields")

            # Get selected model from current form values
            # The UI passes the current configuration including the endpoints array
            endpoints = params.get("endpoints", [])
            if not endpoints:
                raise UserException("Please add an endpoint first")

            # Get the model from the endpoint being configured
            # Keboola passes the entire config, find the model from any endpoint
            model = None
            for endpoint in endpoints:
                if "model" in endpoint and endpoint["model"]:
                    model = endpoint["model"]
                    break

            if not model:
                raise UserException("Please select a model first")

            # Initialize client and fetch fields
            client = OdooClient(
                url=odoo_url,
                database=database,
                username=username,
                api_key=api_key,
            )
            fields_dict = client.get_model_fields(model)

            # Format for Keboola dropdown
            # Sort by field name for better UX
            dropdown_data = []
            for field_name, field_info in sorted(fields_dict.items()):
                field_label = field_info.get('string', field_name)
                field_type = field_info.get('type', 'unknown')
                dropdown_data.append({
                    "value": field_name,
                    "label": f"{field_label} ({field_name}) - {field_type}",
                })

            return {"status": "success", "data": dropdown_data}

        except UserException as e:
            raise e
        except Exception as e:
            raise UserException(f"Failed to load fields: {str(e)}")


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
