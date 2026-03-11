"""
Odoo Extractor Component

Extracts data from Odoo ERP via XML-RPC API.
Uses modern Python 3.9+ type hints and clean orchestrator pattern.
"""

import csv
import logging
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from configuration import Configuration
from keboola.component.base import ComponentBase, sync_action
from keboola.component.exceptions import UserException
from keboola.component.sync_actions import SelectElement
from shared.clients.json2_client import Json2Client
from shared.clients.xmlrpc_client import XmlRpcClient

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


@dataclass
class BridgeTableMetadata:
    """
    Metadata for a many2many/one2many relationship bridge table.

    Bridge tables store relationships between records (e.g., partner → children).
    Each relationship becomes a row with composite primary key.
    """

    table_name: str
    records: list[dict[str, Any]]
    primary_key: list[str]


@dataclass
class SplitTablesResult:
    """
    Result of splitting Odoo records into main table and bridge tables.

    Main table contains scalar fields and flattened many2one relationships.
    Bridge tables contain many2many/one2many relationships as separate records.
    """

    main_records: list[dict[str, Any]]
    bridge_tables: dict[str, BridgeTableMetadata]


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
        """Main extraction logic."""
        if not self.config.model:
            raise UserException("No model configured")

        self._validate_config_for_run()
        self._test_connection()

        self.state = self.get_state_file()
        self._validate_state()
        self._extract_with_paging()

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

    def _validate_config_for_run(self) -> None:
        """Validate configuration before data extraction."""
        errors = []

        if not self.config.database:
            errors.append("Database name is required")

        if not self.config.api_key:
            errors.append("API key is required")

        if self.config.api_protocol == PROTOCOL_XMLRPC and not self.config.username:
            errors.append("Username is required for XML-RPC")

        if not self.config.model:
            errors.append("Model name is required")

        if errors:
            raise UserException(f"Configuration incomplete: {'; '.join(errors)}")

    def _validate_state(self) -> None:
        """Validate model and domain haven't changed since last run."""
        if not self.state:
            logging.info("No previous state found - first run")
            return

        stored_model = self.state.get("model")
        if stored_model and stored_model != self.config.model:
            raise UserException(
                f"Model changed from '{stored_model}' to '{self.config.model}'. "
                "Clear the component state to extract a different model."
            )

        stored_domain = self.state.get("domain", "")
        current_domain = self.config.domain or ""
        if stored_domain != current_domain:
            raise UserException(
                "Domain filter changed since last run. Clear the component state to continue with new filter."
            )

        last_run = self.state.get("last_run", {})
        if last_run:
            logging.info(
                f"Previous run: {last_run.get('timestamp', 'unknown')} - {last_run.get('records_fetched', 0)} records"
            )

    def _test_connection(self) -> None:
        """Test Odoo connection and authentication."""
        if self.client:
            logging.info("Testing Odoo connection...")
            self.client.test_connection()

    def _extract_with_paging(self) -> None:
        """Extract data with cursor-based pagination."""
        logging.info(f"Extracting {self.config.model} -> {self.config.table_name}")

        # Check if we're switching from incremental to full load
        state_last_id = self.state.get("last_id", 0)
        if not self.config.incremental and state_last_id > 0:
            logging.warning(f"Full load mode with existing state (last_id={state_last_id}). Starting fresh extraction.")

        # Initialize cursor from state (incremental) or 0 (full load)
        cursor_id = state_last_id if self.config.incremental else 0

        # Build initial domain with cursor
        domain = self.config.get_domain()
        if cursor_id > 0:
            domain.append(("id", ">", cursor_id))
            logging.info(f"Incremental mode: resuming from ID {cursor_id}")

        table = self.create_out_table_definition(
            name=self.config.table_name,
            incremental=self.config.incremental,
            primary_key=["id"],
        )

        page_num = 1
        total_records = 0
        all_relationship_metadata: dict[str, BridgeTableMetadata] = {}

        # Cursor-based paging loop
        while True:
            logging.info(f"Fetching page {page_num} (cursor: id > {cursor_id}, limit: {self.config.page_size})")

            records = self.client.search_read(
                model=self.config.model,
                domain=domain,
                fields=self.config.fields,
                limit=self.config.page_size,
                order="id asc",
            )

            if not records:
                logging.info("No more records to fetch")
                break

            result = self._split_records(records, self.config.model, self.config.table_name)

            # Write main table (append after first page)
            mode = "a" if page_num > 1 else "w"
            self._write_csv(Path(table.full_path), result.main_records, mode=mode)

            # Accumulate relationship records
            for rel_table_name, rel_data in result.bridge_tables.items():
                if rel_table_name not in all_relationship_metadata:
                    all_relationship_metadata[rel_table_name] = BridgeTableMetadata(
                        table_name=rel_table_name,
                        records=[],
                        primary_key=rel_data.primary_key,
                    )
                all_relationship_metadata[rel_table_name].records.extend(rel_data.records)

            # Update cursor for next page
            max_id = max(r.get("id", 0) for r in records if isinstance(r.get("id"), int))
            cursor_id = max_id

            # Update domain with new cursor
            domain = [d for d in domain if d[0] != "id"]
            domain.append(("id", ">", cursor_id))

            total_records += len(records)
            page_num += 1

            if len(records) < self.config.page_size:
                break

        # Write manifests and relationship tables
        if total_records > 0:
            self.write_manifest(table)

        for rel_table_name, rel_data in all_relationship_metadata.items():
            if rel_data.records:
                rel_table = self.create_out_table_definition(
                    name=rel_data.table_name,
                    incremental=self.config.incremental,
                    primary_key=rel_data.primary_key,
                )
                self._write_csv(Path(rel_table.full_path), rel_data.records)
                self.write_manifest(rel_table)
                logging.info(f"Wrote {len(rel_data.records)} relationship records to {rel_data.table_name}")

        # Write metadata
        if total_records > 0:
            main_table_fields = []
            if Path(table.full_path).exists():
                with open(Path(table.full_path), "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    main_table_fields = list(reader.fieldnames or [])

            # Extract just the table names with records for metadata
            relationship_tables_with_records = {name: data.records for name, data in all_relationship_metadata.items()}

            self._write_metadata_file(
                self.config.model,
                self.config.table_name,
                main_table_fields,
                relationship_tables_with_records,
            )

        logging.info(f"Wrote {total_records} total records to {self.config.table_name}")

        # Get Odoo version for debugging
        odoo_version = "unknown"
        try:
            odoo_version = self.client.get_version()
        except Exception:
            pass

        # Build comprehensive state
        self.state = {
            "model": self.config.model,
            "domain": self.config.domain or "",
            "last_id": cursor_id if self.config.incremental else 0,
            "last_run": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "records_fetched": total_records,
                "incremental": self.config.incremental,
                "odoo_version": odoo_version,
                "page_size": self.config.page_size,
            },
        }

    @staticmethod
    def _split_records(
        records: list[dict[str, Any]],
        model_name: str,
        table_name: str,
    ) -> SplitTablesResult:
        """
        Split records into main table and bridge tables.

        Handles different Odoo field types:
        - many2one: [id, name] → flattened to field_id, field_name in main table
        - many2many/one2many: [id1, id2, ...] → separate bridge table
        - scalar: kept as-is in main table

        Args:
            records: Raw Odoo records
            model_name: Odoo model name (e.g., 'res.partner')
            table_name: Base table name (e.g., 'res_partner.csv')

        Returns:
            SplitTablesResult containing:
            - main_records: Main table records (many2one flattened, scalars preserved)
            - bridge_tables: Dict of table name → BridgeTableMetadata with:
                - table_name: Bridge table name
                - records: List of relationship records
                - primary_key: Composite primary key fields

        Example:
            Input: [{"id": 15, "name": "Azure", "category_id": [5], "child_ids": [27,34]}]
            Output:
                SplitTablesResult(
                    main_records=[{"id": 15, "name": "Azure"}],
                    bridge_tables={
                        "res_partner__category_id.csv": BridgeTableMetadata(
                            table_name="res_partner__category_id.csv",
                            records=[{"partner_id": 15, "category_id": 5}],
                            primary_key=["partner_id", "category_id"]
                        ),
                        "res_partner__child_ids.csv": BridgeTableMetadata(
                            table_name="res_partner__child_ids.csv",
                            records=[
                                {"partner_id": 15, "child_id": 27},
                                {"partner_id": 15, "child_id": 34}
                            ],
                            primary_key=["partner_id", "child_id"]
                        )
                    }
                )
        """
        main_records = []
        relationship_metadata: dict[str, BridgeTableMetadata] = {}

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

                    # Determine relationship field name (remove trailing _ids if present)
                    rel_field_name = key.rstrip("s") if key.endswith("_ids") else key
                    if not rel_field_name.endswith("_id"):
                        rel_field_name = key.replace("_ids", "_id")

                    # Initialize metadata structure for this relationship table
                    if rel_table_name not in relationship_metadata:
                        relationship_metadata[rel_table_name] = BridgeTableMetadata(
                            table_name=rel_table_name,
                            records=[],
                            primary_key=[fk_name, rel_field_name],
                        )

                    # Create relationship records
                    for rel_id in value:
                        relationship_metadata[rel_table_name].records.append(
                            {fk_name: record_id, rel_field_name: rel_id}
                        )
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

        return SplitTablesResult(
            main_records=main_records,
            bridge_tables=relationship_metadata,
        )

    @staticmethod
    def _write_csv(file_path: Path, records: list[dict[str, Any]], mode: str = "w") -> None:
        """Write records to CSV file."""
        if not records:
            return

        file_exists = file_path.exists() and file_path.stat().st_size > 0
        write_header = not file_exists or mode == "w"

        fieldnames = list(records[0].keys())

        if mode == "a" and file_exists:
            with open(file_path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                existing_fieldnames = list(reader.fieldnames or [])
                fieldnames = existing_fieldnames + [f for f in fieldnames if f not in existing_fieldnames]
        else:
            all_keys: set[str] = set()
            for record in records:
                all_keys.update(record.keys())
            for key in all_keys:
                if key not in fieldnames:
                    fieldnames.append(key)

        with open(file_path, mode=mode, encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerows(records)

    def _write_metadata_file(
        self,
        model_name: str,
        table_name: str,
        main_table_fields: list[str],
        relationship_tables: dict[str, list[dict[str, Any]]],
    ) -> None:
        """Write metadata CSV file describing field types and relationships."""
        if not self.client:
            raise UserException("Odoo client not initialized")

        all_fields = self.client.get_model_fields(model_name)

        if main_table_fields:
            fields_to_document = main_table_fields
        elif self.config.fields:
            fields_to_document = self.config.fields
        else:
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
                base_table = table_name if table_name.endswith(".csv") else f"{table_name}.csv"
                metadata_rows.append(
                    MetadataRow(
                        field_name,
                        field_type,
                        relation,
                        base_table,
                        f"{field_name}_id",
                        "",
                    )
                )
                metadata_rows.append(MetadataRow(f"{field_name}_id", "integer", "", base_table, "", ""))
                metadata_rows.append(MetadataRow(f"{field_name}_name", "char", "", base_table, "", ""))

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
                base_table = table_name if table_name.endswith(".csv") else f"{table_name}.csv"
                metadata_rows.append(MetadataRow(field_name, field_type, "", base_table, "", ""))

        # Create table definition for metadata file
        metadata_table = self.create_out_table_definition(
            name=f"metadata__{table_name}",
            incremental=False,
            primary_key=[],
        )

        # Write metadata CSV
        fieldnames = [field.name for field in fields(MetadataRow)]

        with open(metadata_table.full_path, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows([asdict(row) for row in metadata_rows])

        # Write manifest for metadata file
        self.write_manifest(metadata_table)

        logging.info(f"Wrote metadata file: metadata__{table_name}.csv ({len(metadata_rows)} fields)")

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
                return parts[-1].strip()
            return error_str
        else:
            return error_str

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
    def list_models_action(self) -> list[SelectElement]:
        """
        List available Odoo models - sync action for model dropdown.

        Returns:
            Dropdown data with model names
        """
        try:
            models = self.client.list_models()

            models_sorted = sorted(models, key=lambda m: m["model"])

            dropdown_data = [
                SelectElement(
                    value=model["model"],
                    label=f"{model['model']} - {model['name']}",
                )
                for model in models_sorted
            ]

            return dropdown_data

        except UserException as e:
            raise e
        except Exception as e:
            raise UserException(f"Failed to load models: {str(e)}")

    @sync_action("listFields")
    def list_fields_action(self) -> list[SelectElement]:
        """List fields for selected model."""
        try:
            model = self.config.model
            if not model:
                raise UserException("Please select a model first")

            fields_dict = self.client.get_model_fields(model)

            dropdown_data = []
            for field_name, field_info in fields_dict.items():
                if field_name == "_unknown":
                    continue

                field_label = field_info.get("string", field_name)
                field_type = field_info.get("type", "unknown")
                dropdown_data.append(
                    SelectElement(
                        value=field_name,
                        label=f"{field_label} ({field_name}) - {field_type}",
                    )
                )

            return dropdown_data

        except UserException as e:
            raise e
        except Exception as e:
            raise UserException(f"Failed to load fields: {str(e)}")

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

            # Convert to dropdown format
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
