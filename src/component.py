"""
Odoo Extractor Component

Extracts data from Odoo ERP via XML-RPC API.
Uses modern Python 3.9+ type hints and clean orchestrator pattern.
"""

import csv
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from keboola.component.base import ComponentBase, sync_action
from keboola.component.exceptions import UserException

from clients.json2_client import Json2Client
from clients.xmlrpc_client import XmlRpcClient
from configuration import Configuration, OdooEndpoint

PROTOCOL_JSON2 = "json2"
PROTOCOL_XMLRPC = "xmlrpc"
DISPLAY_JSON2 = "JSON-2"
DISPLAY_XMLRPC = "XML-RPC"


@dataclass
class MetadataRow:
    """Schema metadata row for documenting field types and relationships."""

    field_name: str
    field_type: str
    target_model: str
    location: str
    source_column: str
    target_column: str


class Component(ComponentBase):
    """
    Odoo Extractor Component.

    Connects to Odoo via XML-RPC and extracts data from configured models.
    Follows clean orchestrator pattern with delegated methods.
    """

    def __init__(self) -> None:
        """Initialize component."""
        super().__init__()
        self.state: dict[str, Any] = {}
        self.config = Configuration(**self.configuration.parameters)
        self.client = self._initialize_client(self.config)

    def run(self) -> None:
        """
        Main extraction logic - clean orchestrator.

        Orchestrates the extraction workflow by delegating to well-named methods.
        Keeps this method concise (~20-30 lines) for readability.
        """
        if not self.config.endpoints:
            raise UserException("No endpoints configured")

        self._test_connection()

        self.state = self.get_state_file()

        for endpoint in self.config.endpoints:
            self._extract_endpoint(endpoint)

        if self.state:
            self.write_state_file(self.state)

        logging.info("Extraction completed successfully")

    def _initialize_client(self, params: Configuration) -> XmlRpcClient | Json2Client:
        """
        Initialize and return appropriate Odoo client based on api_protocol config.

        Args:
            params: Configuration object

        Returns:
            Initialized XmlRpcClient or Json2Client based on api_protocol setting
        """
        ClientClass = Json2Client if params.api_protocol == PROTOCOL_JSON2 else XmlRpcClient

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

        # Handle no records case with early return
        if not records:
            logging.warning(f"No records found for {endpoint.model}")
            # Still create metadata file to document schema
            self._write_metadata_file(
                endpoint.model,
                endpoint.table_name,
                [],
                {},
                endpoint,
            )
            return

        # Create output table
        table = self.create_out_table_definition(
            name=endpoint.table_name,
            incremental=endpoint.incremental,
            primary_key=endpoint.primary_key or ["id"],
        )

        # Split records into main table and relationship tables
        main_records, relationship_tables = self._split_records(records, endpoint.model, endpoint.table_name)

        # Write main table
        self._write_csv(Path(table.full_path), main_records)

        # Save manifest for main table
        self.write_manifest(table)

        # Write relationship tables (if any)
        for rel_table_name, rel_records in relationship_tables.items():
            if rel_records:  # Only create table if there are records
                rel_table = self.create_out_table_definition(
                    name=rel_table_name,
                    incremental=False,  # Relationship tables always full refresh
                    primary_key=[],  # No primary key for relationship tables
                )
                self._write_csv(Path(rel_table.full_path), rel_records)
                self.write_manifest(rel_table)
                logging.info(f"Wrote {len(rel_records)} relationship records to {rel_table_name}")

        # Write metadata file describing schema and relationships
        main_table_fields = list(main_records[0].keys()) if main_records else []
        self._write_metadata_file(
            endpoint.model,
            endpoint.table_name,
            main_table_fields,
            relationship_tables,
            endpoint,
        )

        logging.info(f"Wrote {len(records)} records to {endpoint.table_name}")

        # Update state for incremental loading
        if endpoint.incremental and records:
            max_id = max(record.get("id", 0) for record in records if isinstance(record.get("id"), int))

            # Update nested state structure in shared self.state
            if "endpoints" not in self.state:
                self.state["endpoints"] = {}
            if endpoint.table_name not in self.state["endpoints"]:
                self.state["endpoints"][endpoint.table_name] = {}

            self.state["endpoints"][endpoint.table_name]["last_id"] = max_id
            # Note: State is written once at the end of run(), not here
            logging.info(f"Updated state: last_id = {max_id}")

    @staticmethod
    def _split_records(
        records: list[dict[str, Any]],
        model_name: str,
        table_name: str,
    ) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        """
        Split records into main table and relationship tables.

        Handles different Odoo field types:
        - many2one: [id, name] → flattened to field_id, field_name in main table
        - many2many/one2many: [id1, id2, ...] → separate relationship table
        - scalar: kept as-is in main table

        Args:
            records: Raw Odoo records
            model_name: Odoo model name (e.g., 'res.partner')
            table_name: Base table name (e.g., 'res_partner.csv')

        Returns:
            Tuple of:
            - Main table records (many2one flattened, scalars preserved)
            - Dict of relationship table name → relationship records

        Example:
            Input: [{"id": 15, "name": "Azure", "category_id": [5], "child_ids": [27,34]}]
            Output:
                Main: [{"id": 15, "name": "Azure"}]
                Relationships: {
                    "res_partner__category_id.csv": [
                        {"partner_id": 15, "category_id": 5}
                    ],
                    "res_partner__child_ids.csv": [
                        {"partner_id": 15, "child_id": 27},
                        {"partner_id": 15, "child_id": 34}
                    ]
                }
        """
        main_records = []
        relationship_tables: dict[str, list[dict[str, Any]]] = {}

        # Extract foreign key name from model (e.g., 'res.partner' → 'partner_id')
        # Use the last part of the model name
        fk_name = model_name.split(".")[-1] + "_id"

        # Base name for relationship tables (remove .csv extension if present)
        base_name = table_name.replace(".csv", "")

        for record in records:
            main_record: dict[str, Any] = {}
            record_id = record.get("id")

            for key, value in record.items():
                if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], int):
                    # many2one field: [id, name] → flatten to main table
                    main_record[f"{key}_id"] = value[0]
                    main_record[f"{key}_name"] = value[1]

                elif isinstance(value, list) and value and all(isinstance(v, int) for v in value):
                    # many2many or one2many: [id1, id2, ...] → split to relationship table
                    rel_table_name = f"{base_name}__{key}.csv"

                    if rel_table_name not in relationship_tables:
                        relationship_tables[rel_table_name] = []

                    # Determine relationship field name (remove trailing _ids if present)
                    rel_field_name = key.rstrip("s") if key.endswith("_ids") else key
                    if not rel_field_name.endswith("_id"):
                        rel_field_name = key.replace("_ids", "_id")

                    # Create relationship records
                    for rel_id in value:
                        relationship_tables[rel_table_name].append({fk_name: record_id, rel_field_name: rel_id})
                    # Don't include this field in main record

                elif isinstance(value, list):
                    # Empty list or non-integer list → skip
                    # Don't add to main table or relationship table
                    pass

                elif value is False:
                    # Odoo uses False for null values
                    main_record[key] = None

                else:
                    # Regular scalar field
                    main_record[key] = value

            main_records.append(main_record)

        return main_records, relationship_tables

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

    def _write_metadata_file(
        self,
        model_name: str,
        table_name: str,
        main_table_fields: list[str],
        relationship_tables: dict[str, list[dict[str, Any]]],
        endpoint: OdooEndpoint,
    ) -> None:
        """
        Write metadata CSV file describing field types and relationships.

        Creates __metadata__{model}.csv file with schema information to help users
        understand field types and build SQL joins between main and relationship tables.

        Args:
            model_name: Odoo model name (e.g., 'res.partner')
            table_name: Main table name (e.g., 'res_partner')
            main_table_fields: List of field names in the main table
            relationship_tables: Dict of relationship table names → records
            endpoint: Endpoint configuration with field selection
        """
        if not self.client:
            raise UserException("Odoo client not initialized")

        # Get field metadata from Odoo
        all_fields = self.client.get_model_fields(model_name)

        # Determine which fields to document
        if main_table_fields:
            # We have records - document fields that appear in main table
            fields_to_document = main_table_fields
        elif endpoint.fields:
            # No records but user selected specific fields - document those
            fields_to_document = endpoint.fields
        else:
            # No records and no field selection - document all Odoo fields
            fields_to_document = list(all_fields.keys())

        # Build metadata rows
        metadata_rows: list[MetadataRow] = []

        # Process each field
        for field_name in fields_to_document:
            # Skip flattened many2one fields (_id, _name suffixes) - we'll handle them separately
            if field_name.endswith("_id") or field_name.endswith("_name"):
                # Check if this is a flattened many2one field
                original_field = field_name.rsplit("_", 1)[0]
                if original_field in all_fields and all_fields[original_field].get("type") == "many2one":
                    # This is a flattened field, skip it here
                    continue

            field_meta = all_fields.get(field_name, {})
            field_type = field_meta.get("type", "")
            relation = field_meta.get("relation", "")

            if field_type == "many2one":
                # Many2one: Create 3 rows (original + _id + _name flattened columns)
                metadata_rows.append(
                    MetadataRow(
                        field_name,
                        field_type,
                        relation,
                        f"{table_name}.csv",
                        f"{field_name}_id",
                        "",
                    )
                )
                metadata_rows.append(MetadataRow(f"{field_name}_id", "integer", "", f"{table_name}.csv", "", ""))
                metadata_rows.append(MetadataRow(f"{field_name}_name", "char", "", f"{table_name}.csv", "", ""))

            elif field_type in ("many2many", "one2many"):
                # Many2many/one2many: Check if relationship table exists
                rel_table_name = f"{table_name}__{field_name}.csv"
                if rel_table_name in relationship_tables:
                    # Determine relationship column name
                    rel_field_name = field_name.rstrip("s") if field_name.endswith("_ids") else field_name
                    if not rel_field_name.endswith("_id"):
                        rel_field_name = field_name.replace("_ids", "_id")

                    # Determine source FK name
                    fk_name = model_name.split(".")[-1] + "_id"

                    metadata_rows.append(
                        MetadataRow(
                            field_name,
                            field_type,
                            relation,
                            rel_table_name,
                            fk_name,
                            rel_field_name,
                        )
                    )

            else:
                # Scalar field
                metadata_rows.append(MetadataRow(field_name, field_type, "", f"{table_name}.csv", "", ""))

        # Write metadata CSV
        metadata_path = Path(self.tables_out_path) / f"__metadata__{table_name}.csv"
        fieldnames = [field.name for field in fields(MetadataRow)]

        with open(metadata_path, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows([asdict(row) for row in metadata_rows])

        logging.info(f"Wrote metadata file: __metadata__{table_name}.csv ({len(metadata_rows)} fields)")

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
            # All validation happens in Configuration __init__
            # Just extract the values we need
            odoo_url = self.config.odoo_url
            database = self.config.database
            username = self.config.username
            api_key = self.config.api_key
            selected_protocol = self.config.api_protocol

            # Step 1: Check protocol availability (no auth required)
            protocols_available = {}
            odoo_version = None

            # Initialize clients
            xmlrpc_client = XmlRpcClient(odoo_url, database, username, api_key)
            json2_client = Json2Client(odoo_url, database, username, api_key)

            # Check XML-RPC availability
            try:
                version = xmlrpc_client.get_version()
                protocols_available[DISPLAY_XMLRPC] = True
                odoo_version = version
            except Exception as e:
                protocols_available[DISPLAY_XMLRPC] = False
                logging.debug(f"XML-RPC availability check failed: {e}")

            # Check JSON-2 availability
            try:
                version = json2_client.get_version()
                protocols_available[DISPLAY_JSON2] = True
                if not odoo_version:
                    odoo_version = version
            except Exception as e:
                protocols_available[DISPLAY_JSON2] = False
                logging.debug(f"JSON-2 availability check failed: {e}")

            # Fail if no version detected from any protocol
            if not odoo_version:
                raise UserException("Cannot connect to Odoo instance at this URL")

            # Step 2: Build "Supports" section
            supports_parts = []
            for protocol in [DISPLAY_JSON2, DISPLAY_XMLRPC]:
                symbol = "✓" if protocols_available.get(protocol, False) else "✗"
                supports_parts.append(f"{protocol} {symbol}")
            supports_str = ", ".join(supports_parts)

            # Step 3: Test authentication for selected protocol only
            selected_client = None
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
                    short_error = self._extract_short_error(e)
                    return {
                        "status": "error",
                        "message": (
                            f"Odoo {odoo_version}. Supports: {supports_str}. "
                            f"Authentication failed using {DISPLAY_JSON2} ({short_error})"
                        ),
                    }
            else:  # xmlrpc (default)
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
                    short_error = self._extract_short_error(e)
                    return {
                        "status": "error",
                        "message": (
                            f"Odoo {odoo_version}. Supports: {supports_str}. "
                            f"Authentication failed using {DISPLAY_XMLRPC} ({short_error})"
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
            models = self.client.list_models()

            models_sorted = sorted(models, key=lambda m: m["model"])

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
            if not self.config.endpoints:
                raise UserException("Please add an endpoint first")

            model = None
            for endpoint in self.config.endpoints:
                if endpoint.model:
                    model = endpoint.model
                    break

            if not model:
                raise UserException("Please select a model first")

            fields_dict = self.client.get_model_fields(model)

            dropdown_data = []
            for field_name, field_info in fields_dict.items():
                # Filter out _unknown placeholder field
                if field_name == "_unknown":
                    continue

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
