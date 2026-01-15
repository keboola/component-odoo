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
from clients.xmlrpc_client import XmlRpcClient
from clients.json2_client import Json2Client


class Component(ComponentBase):
    """
    Odoo Extractor Component.

    Connects to Odoo via XML-RPC and extracts data from configured models.
    Follows clean orchestrator pattern with delegated methods.
    """

    def __init__(self) -> None:
        """Initialize component."""
        super().__init__()
        self.client: XmlRpcClient | Json2Client | None = None
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

    def _initialize_client(self, params: Configuration) -> XmlRpcClient | Json2Client:
        """
        Initialize and return appropriate Odoo client based on api_protocol config.

        Args:
            params: Configuration object

        Returns:
            Initialized XmlRpcClient or Json2Client based on api_protocol setting
        """
        ClientClass = Json2Client if params.api_protocol == "json2" else XmlRpcClient

        return ClientClass(
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
        logging.info(f"Extracting {endpoint.model} -> {endpoint.table_name}")

        # Get state for incremental loading (use shared self.state)
        # Use nested structure: state["endpoints"][table_name]["last_id"]
        if not endpoint.incremental:
            last_id = 0
        else:
            endpoints_state = self.state.get("endpoints", {})
            endpoint_state = endpoints_state.get(endpoint.table_name, {})
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
            name=endpoint.table_name,
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
            if endpoint.table_name not in self.state["endpoints"]:
                self.state["endpoints"][endpoint.table_name] = {}

            self.state["endpoints"][endpoint.table_name]["last_id"] = max_id
            # Note: State is written once at the end of run(), not here
            logging.info(f"Updated state: last_id = {max_id}")

        logging.info(f"Wrote {len(records)} records to {endpoint.table_name}")

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

        # Preserve field order from first record, then add any additional fields
        # This keeps Odoo's original field order instead of alphabetical
        fieldnames = list(records[0].keys())

        # Add any fields that appear in other records but not in first record
        all_keys: set[str] = set()
        for record in records:
            all_keys.update(record.keys())

        for key in all_keys:
            if key not in fieldnames:
                fieldnames.append(key)

        # Write CSV
        with open(file_path, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)

    # === Helper Methods ===

    def _extract_short_error(self, exception: Exception) -> str:
        """Extract concise error message from exception."""
        error_str = str(exception)

        # Map common errors to short forms
        if "Invalid apikey" in error_str or "Invalid API key" in error_str:
            return "invalid API key"
        elif "401" in error_str:
            return "invalid API key"
        elif "403" in error_str or "forbidden" in error_str.lower():
            return "access forbidden"
        elif "404" in error_str:
            return "endpoint not found"
        elif "invalid credentials" in error_str.lower():
            return "invalid credentials"
        elif "authentication failed" in error_str.lower():
            # Extract the specific reason if present
            parts = error_str.split(":")
            if len(parts) > 1:
                return parts[-1].strip()[:50]
            return error_str[:50]
        else:
            # Keep it short, max 50 chars
            return error_str[:50] + "..." if len(error_str) > 50 else error_str

    # === Sync Actions (UI buttons) ===

    @sync_action("testConnection")
    def test_connection_action(self) -> dict[str, str]:
        """
        Test connection showing:
        1. Odoo version
        2. Protocol availability (✓/✗ for both JSON-2 and XML-RPC)
        3. Authentication status for selected protocol only
        4. Model count if authentication succeeds

        Message format:
        "Odoo {version}. Supports: JSON-2 {✓/✗}, XML-RPC {✓/✗}. Authenticated using {protocol}, {N} models"

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
            selected_protocol = params.get("api_protocol", "xmlrpc")

            if not all([odoo_url, database, username, api_key]):
                raise UserException(
                    "All connection fields are required: Odoo URL, Database, Username, and API Key"
                )

            # Step 1: Check protocol availability (no auth required)
            protocols_available = {}
            odoo_version = None

            # Initialize clients
            xmlrpc_client = XmlRpcClient(odoo_url, database, username, api_key)
            json2_client = Json2Client(odoo_url, database, username, api_key)

            # Check XML-RPC availability
            try:
                version = xmlrpc_client.get_version()
                protocols_available["XML-RPC"] = True
                odoo_version = version
            except Exception as e:
                protocols_available["XML-RPC"] = False
                logging.debug(f"XML-RPC availability check failed: {e}")

            # Check JSON-2 availability
            try:
                version = json2_client.get_version()
                protocols_available["JSON-2"] = True
                if not odoo_version:
                    odoo_version = version
            except Exception as e:
                protocols_available["JSON-2"] = False
                logging.debug(f"JSON-2 availability check failed: {e}")

            # Fail if no version detected from any protocol
            if not odoo_version:
                raise UserException("Cannot connect to Odoo instance at this URL")

            # Step 2: Build "Supports" section
            supports_parts = []
            for protocol in ["JSON-2", "XML-RPC"]:
                symbol = "✓" if protocols_available.get(protocol, False) else "✗"
                supports_parts.append(f"{protocol} {symbol}")
            supports_str = ", ".join(supports_parts)

            # Step 3: Test authentication for selected protocol only
            selected_client = None
            auth_message = ""

            if selected_protocol == "json2":
                if not protocols_available["JSON-2"]:
                    return {
                        "status": "error",
                        "message": (
                            f"Odoo {odoo_version}. Supports: {supports_str}. "
                            "JSON-2 not available on this instance"
                        ),
                    }
                try:
                    json2_client.test_connection()
                    selected_client = json2_client
                    auth_message = "Authenticated using JSON-2"
                except Exception as e:
                    short_error = self._extract_short_error(e)
                    return {
                        "status": "error",
                        "message": (
                            f"Odoo {odoo_version}. Supports: {supports_str}. "
                            f"Authentication failed using JSON-2 ({short_error})"
                        ),
                    }
            else:  # xmlrpc (default)
                if not protocols_available["XML-RPC"]:
                    return {
                        "status": "error",
                        "message": (
                            f"Odoo {odoo_version}. Supports: {supports_str}. "
                            "XML-RPC not available on this instance"
                        ),
                    }
                try:
                    xmlrpc_client.test_connection()
                    selected_client = xmlrpc_client
                    auth_message = "Authenticated using XML-RPC"
                except Exception as e:
                    short_error = self._extract_short_error(e)
                    return {
                        "status": "error",
                        "message": (
                            f"Odoo {odoo_version}. Supports: {supports_str}. "
                            f"Authentication failed using XML-RPC ({short_error})"
                        ),
                    }

            # Step 4: Get model count
            model_suffix = ""
            try:
                models = selected_client.list_models()
                model_suffix = f", {len(models)} models"
            except Exception as e:
                logging.warning(f"Could not fetch model count: {e}")

            # Step 5: Build final success message
            message = f"Odoo {odoo_version}. Supports: {supports_str}. {auth_message}{model_suffix}"

            return {"status": "success", "message": message}

        except UserException as e:
            raise e
        except Exception as e:
            raise UserException(f"Connection test failed: {str(e)}")

    @sync_action("listModels")
    def list_models_action(self) -> list[dict[str, str]]:
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
            client = XmlRpcClient(
                url=odoo_url,
                database=database,
                username=username,
                api_key=api_key,
            )
            models = client.list_models()

            # Sort by technical name for natural categorization
            models_sorted = sorted(models, key=lambda m: m["model"])

            # Format for Keboola dropdown: [{"value": "...", "label": "..."}]
            dropdown_data = [
                {
                    "value": model["model"],
                    "label": f"{model['model']} - {model['name']}",
                }
                for model in models_sorted
            ]

            return dropdown_data

        except UserException as e:
            raise e
        except Exception as e:
            raise UserException(f"Failed to load models: {str(e)}")

    @sync_action("listFields")
    def list_fields_action(self) -> list[dict[str, str]]:
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
            client = XmlRpcClient(
                url=odoo_url,
                database=database,
                username=username,
                api_key=api_key,
            )
            fields_dict = client.get_model_fields(model)

            # Format for Keboola dropdown in Odoo's original order
            dropdown_data = []
            for field_name, field_info in fields_dict.items():
                field_label = field_info.get("string", field_name)
                field_type = field_info.get("type", "unknown")
                dropdown_data.append(
                    {
                        "value": field_name,
                        "label": f"{field_label} ({field_name}) - {field_type}",
                    }
                )

            return dropdown_data

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
