"""
Odoo Extractor Component

Extracts data from Odoo ERP via XML-RPC API.
Handles many2one field flattening with consistent column generation.
"""

import csv
import logging
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from configuration import Configuration
from keboola.component.base import ComponentBase
from keboola.component.exceptions import UserException
from shared.connection import PROTOCOL_XMLRPC
from shared.odoo_base import OdooSyncActionsMixin, initialize_client

INCREMENTAL_FIELD = "write_date"


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


class Component(OdooSyncActionsMixin, ComponentBase):
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
        self.client = initialize_client(self.config)
        self._fields_cache: dict[str, dict[str, Any]] = {}

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
        """Extract data, paging by id and filtering by write_date in incremental mode."""
        logging.info(f"Extracting {self.config.model} -> {self.config.table_name}")

        many2one_fields = self._get_many2one_fields()
        tracks_changes = INCREMENTAL_FIELD in self._model_fields(self.config.model)
        # write_date incremental captures created *and* modified records; models without a
        # write_date field keep the classic id-based incremental (new records only).
        use_write_date = self.config.incremental and tracks_changes
        last_write_date = self._incremental_cursor(tracks_changes)

        # Incremental runs fetch everything modified since the last run, regardless of id
        base_domain = self.config.get_domain()
        if last_write_date:
            base_domain.append((INCREMENTAL_FIELD, ">=", last_write_date))
            logging.info(f"Incremental mode: fetching records modified since {last_write_date}")

        # Only fetch write_date when it drives the cursor; otherwise it would leak into the
        # output as an extra column (drop_write_date is gated the same way).
        fields_to_fetch = self._fields_to_fetch(use_write_date)
        drop_write_date = use_write_date and bool(self.config.fields) and INCREMENTAL_FIELD not in self.config.fields

        table = self.create_out_table_definition(
            name=self.config.table_name,
            incremental=self.config.incremental,
            primary_key=["id"],
        )

        page_num = 1
        total_records = 0
        # For write_date models the id cursor only paginates within a run (starts at 0); for
        # models without write_date it also resumes incremental extraction across runs.
        cursor_id = self._id_cursor_start(tracks_changes)
        max_write_date = last_write_date
        # Watermark captured BEFORE the first fetch: a record modified while we page can carry a
        # write_date newer than an already-read page, so the persisted cursor must not advance
        # past the run start or that modification is never re-selected on a later run.
        run_start = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        all_relationship_metadata: dict[str, BridgeTableMetadata] = {}

        # Cursor-based paging loop (the id cursor only paginates within a single run)
        while True:
            logging.info(f"Fetching page {page_num} (cursor: id > {cursor_id}, limit: {self.config.page_size})")

            domain = [*base_domain, ("id", ">", cursor_id)] if cursor_id > 0 else base_domain
            records = self.client.search_read(
                model=self.config.model,
                domain=domain,
                fields=fields_to_fetch,
                limit=self.config.page_size,
                order="id asc",
            )

            if not records:
                logging.info("No more records to fetch")
                break

            max_write_date = self._max_write_date(records, max_write_date)
            if drop_write_date:
                for record in records:
                    record.pop(INCREMENTAL_FIELD, None)

            result = self._split_records(records, self.config.model, self.config.table_name, many2one_fields)

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
            cursor_id = max(r.get("id", 0) for r in records if isinstance(r.get("id"), int))

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

        # Cap the persisted cursor at the run start: min(run_start, observed max) re-reads a
        # bounded overlap on the next run (idempotent upsert on `id`) rather than skipping a
        # record modified mid-run. An empty cursor ("" = full sweep) is preserved.
        if max_write_date:
            max_write_date = min(max_write_date, run_start)

        # Build comprehensive state
        self.state = {
            "model": self.config.model,
            "domain": self.config.domain or "",
            "last_write_date": max_write_date if use_write_date else "",
            "last_run": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "records_fetched": total_records,
                "incremental": self.config.incremental,
                "odoo_version": odoo_version,
                "page_size": self.config.page_size,
            },
        }
        # Models without write_date resume by id instead (new records only).
        if self.config.incremental and not tracks_changes:
            self.state["last_id"] = cursor_id

    @staticmethod
    def _split_records(
        records: list[dict[str, Any]],
        model_name: str,
        table_name: str,
        many2one_fields: set[str] | None = None,
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
            many2one_fields: Set of field names known to be many2one type.
                Used to ensure consistent _id/_name columns even when the value is False.

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
        many2one_fields = many2one_fields or set()
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
                    if key in many2one_fields:
                        main_record[f"{key}_id"] = None
                        main_record[f"{key}_name"] = None
                    else:
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
        all_fields = self._model_fields(model_name)

        if main_table_fields:
            fields_to_document = main_table_fields
        elif self.config.fields:
            fields_to_document = self.config.fields
        else:
            fields_to_document = list(all_fields.keys())

        # Build metadata rows
        metadata_rows: list[MetadataRow] = []
        documented_many2one: set[str] = set()

        # Process each field
        for field_name in fields_to_document:
            # Skip flattened many2one fields (_id, _name suffixes) - we'll handle them separately
            if field_name.endswith("_id") or field_name.endswith("_name"):
                # Check if this is a flattened many2one field
                original_field = field_name.rsplit("_", 1)[0]
                if original_field in all_fields and all_fields[original_field].get("type") == "many2one":
                    # Track and generate metadata for this many2one if not already done
                    if original_field not in documented_many2one:
                        documented_many2one.add(original_field)
                        field_meta = all_fields[original_field]
                        relation = field_meta.get("relation", "")
                        base_table = table_name if table_name.endswith(".csv") else f"{table_name}.csv"
                        metadata_rows.append(
                            MetadataRow(original_field, "many2one", relation, base_table, f"{original_field}_id", "")
                        )
                        metadata_rows.append(MetadataRow(f"{original_field}_id", "integer", "", base_table, "", ""))
                        metadata_rows.append(MetadataRow(f"{original_field}_name", "char", "", base_table, "", ""))
                    continue

            field_meta = all_fields.get(field_name, {})
            field_type = field_meta.get("type", "")
            relation = field_meta.get("relation", "")

            if field_type == "many2one" and field_name not in documented_many2one:
                # Many2one: Create 3 rows (original + _id + _name flattened columns)
                documented_many2one.add(field_name)
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

    def _model_fields(self, model_name: str) -> dict[str, Any]:
        """Fetch and cache field metadata for a model (avoids duplicate API calls)."""
        if not self.client:
            raise UserException("Odoo client not initialized")
        if model_name not in self._fields_cache:
            self._fields_cache[model_name] = self.client.get_model_fields(model_name)
        return self._fields_cache[model_name]

    def _incremental_cursor(self, tracks_changes: bool) -> str:
        """Return the write_date to resume from, or an empty string for a full sweep."""
        if not self.config.incremental or not tracks_changes:
            # Full load, or a model without write_date (handled by the id cursor instead).
            return ""

        cursor = str(self.state.get("last_write_date", ""))
        if not cursor and self.state.get("last_id"):
            logging.info(
                "State was created by the id-based cursor - running one full sweep to pick up "
                "records modified since they were first extracted."
            )
        return cursor

    def _id_cursor_start(self, tracks_changes: bool) -> int:
        """
        Starting value for the id paging cursor.

        For models with a write_date field this is always 0 - the id cursor only paginates
        within a single run. For models WITHOUT a write_date field it doubles as the
        incremental resume point (classic append-only ``id > last_id`` behaviour), so new
        records are still fetched cheaply instead of re-sweeping the whole model every run.
        """
        if not self.config.incremental or tracks_changes:
            return 0

        try:
            last_id = int(self.state.get("last_id", 0) or 0)
        except (TypeError, ValueError):
            last_id = 0

        logging.warning(
            f"Model {self.config.model} has no '{INCREMENTAL_FIELD}' field - using id-based "
            f"incremental (resuming from id {last_id}); records modified after creation are "
            "not re-fetched for this model."
        )
        return last_id

    def _fields_to_fetch(self, use_write_date: bool) -> list[str] | None:
        """Add write_date to the requested fields so the write_date cursor can be advanced."""
        if not self.config.fields or not use_write_date:
            return self.config.fields
        if INCREMENTAL_FIELD in self.config.fields:
            return self.config.fields
        return [*self.config.fields, INCREMENTAL_FIELD]

    @staticmethod
    def _max_write_date(records: list[dict[str, Any]], current: str) -> str:
        """Highest write_date seen so far - the cursor for the next run."""
        write_dates = [str(r[INCREMENTAL_FIELD]) for r in records if r.get(INCREMENTAL_FIELD)]
        return max([current, *write_dates]) if write_dates else current

    def _get_many2one_fields(self) -> set[str]:
        """Get the set of many2one field names for the configured model."""
        all_fields = self._model_fields(self.config.model)
        many2one = {name for name, meta in all_fields.items() if meta.get("type") == "many2one"}
        if self.config.fields:
            many2one = many2one & set(self.config.fields)
        logging.info(f"Identified {len(many2one)} many2one fields for consistent column handling")
        return many2one


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
