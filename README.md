# Odoo Extractor

Extract data from Odoo ERP systems using XML-RPC or JSON-2 protocols with dynamic model/field discovery and modern Python 3.13 implementation.

## Features

### Core Capabilities
- ✅ **Dual Protocol Support** - Choose between XML-RPC (all versions) or JSON-2 (Odoo 19+, 2-3x faster)
- ✅ **Dynamic Model Discovery** - Browse and select from hundreds of Odoo models via UI
- ✅ **Field Discovery** - Automatically load field definitions for selected models
- ✅ **Database Discovery** - Auto-discover available databases on Odoo instance
- ✅ **Test Connection** - Validate credentials before running extractions
- ✅ **Configuration Rows** - Modern Keboola pattern: one row per model
- ✅ **Incremental Loading** - Cursor-based state tracking for efficient updates
- ✅ **Smart Relationship Handling** - Automatically splits many2many/one2many into normalized tables

### Technical Highlights
- ✅ **Modern Type Hints** - Python 3.13 with `list[str]`, `dict[str, Any]`, `int | None`
- ✅ **Sync Actions** - Dynamic UI with testConnection, listDatabases, listModels, listFields
- ✅ **Cursor-Based Pagination** - Efficient `id > cursor_id` pagination with configurable page size
- ✅ **Client Abstraction** - Separate XmlRpcClient and Json2Client implementations
- ✅ **Code Quality** - Ruff formatted, type-checked, dataclass-driven architecture

## Configuration

### Configuration Rows Pattern

This component uses **configuration rows** - the modern Keboola architecture where:
- Each configuration row = one Odoo model extraction
- Component runs once per row (independent executions)
- Each row has its own state (incremental tracking)
- Add multiple rows to extract multiple models

**Benefits:**
- ✅ Isolated state per model (no conflicts)
- ✅ Independent execution (parallel processing)
- ✅ Easy to add/remove models (just add/delete rows)
- ✅ Clear separation of concerns

### Global Configuration

Set up your Odoo connection once (shared across all rows):

**Connection Parameters:**
- `odoo_url` - Odoo instance URL (e.g., `https://demo.odoo.com`)
- `database` - Database name (use **List Databases** button to discover)
- `username` - User email/login (optional for JSON-2 protocol)
- `#api_key` - API key or password (encrypted field)
- `api_protocol` - Protocol to use:
  - `xmlrpc` - XML-RPC (all Odoo versions, universal)
  - `json2` - JSON-2 (Odoo 19+, 2-3x faster, modern)

**UI Features:**
- **Test Connection** button - Validates credentials and protocol availability
- **List Databases** button - Auto-discovers available databases on the instance

### Row Configuration (Per Model)

Each configuration row defines extraction for ONE Odoo model:

**Required Parameters:**
- `model` - Odoo model name (e.g., `res.partner`, `sale.order`)
- `output_table` - Output table name (e.g., `customers`, `sales_orders`)

**Optional Parameters:**
- `fields` - Field list to extract (empty = extract all fields)
- `domain` - Odoo domain filter (e.g., `[["state", "=", "sale"]]`)
- `incremental` - Enable incremental loading (default: `false`)
- `page_size` - Records per page for pagination (default: `1000`)
- `primary_key` - Primary key columns (default: `["id"]`)

**UI Features:**
- **Model Dropdown** - Select from 100+ models (autoloaded via sync action)
- **Fields Multi-Select** - Choose fields to extract (autoloaded based on model)
- Shows field labels, types, and technical names

## API Protocol Comparison

### XML-RPC (Universal)
- ✅ **Compatibility:** All Odoo versions (8.0+)
- ✅ **Stability:** Battle-tested, widely used
- ✅ **Username required:** Must provide username
- ⚠️ **Performance:** Slower than JSON-2 (XML overhead)

### JSON-2 (Modern - Odoo 19+)
- ✅ **Performance:** 2-3x faster than XML-RPC
- ✅ **Modern:** Native JSON, smaller payloads
- ✅ **No username needed:** API key is sufficient
- ⚠️ **Compatibility:** Odoo 19.0+ only

**Recommendation:** Use JSON-2 if you're on Odoo 19+, otherwise XML-RPC.

## Example Configuration

### Global Config (Connection)
```json
{
  "parameters": {
    "odoo_url": "https://demo.odoo.com",
    "database": "demo",
    "username": "admin",
    "#api_key": "admin",
    "api_protocol": "xmlrpc"
  }
}
```

### Configuration Row #1 (Partners - Full Extract)
```json
{
  "parameters": {
    "model": "res.partner",
    "output_table": "customers",
    "fields": ["id", "name", "email", "phone", "country_id", "child_ids"],
    "incremental": false,
    "page_size": 1000,
    "primary_key": ["id"]
  }
}
```

### Configuration Row #2 (Sales Orders - Incremental)
```json
{
  "parameters": {
    "model": "sale.order",
    "output_table": "sales_orders",
    "domain": [["state", "=", "sale"]],
    "incremental": true,
    "page_size": 500,
    "primary_key": ["id"]
  }
}
```

## Supported Models

Extract from any Odoo model:

- **Contacts**: `res.partner`, `res.users`, `res.company`
- **Sales**: `sale.order`, `sale.order.line`
- **Invoicing**: `account.move`, `account.move.line`
- **Inventory**: `product.product`, `product.template`, `stock.move`
- **CRM**: `crm.lead`, `crm.stage`
- **HR**: `hr.employee`, `hr.department`
- And many more!

Use the **List Models** button in the UI to see all available models for your Odoo instance.

## Handling Relational Fields

The extractor automatically handles Odoo's relational data structures by creating properly normalized tables:

### many2one Fields (Flattened in Main Table)

**Example:** `country_id: [233, "United States"]`

Flattened into the main table as two columns:

```csv
id,name,country_id_id,country_id_name
15,Azure Interior,233,United States
```

### many2many & one2many Fields (Auto-Split into Separate Tables)

**Example:** Partner with categories and child contacts

**Input record:**
```json
{
  "id": 15,
  "name": "Azure Interior",
  "category_id": [5],
  "child_ids": [27, 34, 28]
}
```

**Output: 3 separate tables** (normalized structure)

**`customers.csv`** (main table):
```csv
id,name
15,Azure Interior
```

**`customers__category_id.csv`** (relationship table):
```csv
partner_id,category_id
15,5
```

**Primary Key:** `["partner_id", "category_id"]` (composite)

**`customers__child_ids.csv`** (relationship table):
```csv
partner_id,child_id
15,27
15,34
15,28
```

**Primary Key:** `["partner_id", "child_id"]` (composite)

### Bridge Table Incremental Support

Bridge tables (relationship tables) now support incremental mode:

- ✅ **Incremental mode matches main table** - If main table uses incremental, so do bridge tables
- ✅ **Composite primary keys** - Prevents duplicate relationships in storage
- ✅ **Automatic creation** - No configuration needed
- ⚠️ **Known trade-off:** Deleted relationships remain until full reload (accepted limitation)

**Example:** If `customers` uses `incremental: true`, then `customers__child_ids` also uses incremental mode with composite PK `["partner_id", "child_id"]`.

### Why Auto-Split?

✅ **Proper relational structure** - Industry-standard data modeling
✅ **Easy SQL joins** - `JOIN customers__category_id ON id = partner_id`
✅ **BI tool friendly** - Works seamlessly with Tableau, PowerBI, Looker
✅ **No data loss** - Preserves all relationship information
✅ **Scalable** - Handles large many2many datasets efficiently

### Field Type Summary

| Odoo Field Type | Storage Strategy | Example Output |
|-----------------|------------------|----------------|
| **Scalar** (text, number, date) | Main table column | `email: "user@example.com"` |
| **many2one** | Flattened in main table | `country_id_id: 233`<br>`country_id_name: "United States"` |
| **many2many** | Separate bridge table with composite PK | `customers__category_id.csv` |
| **one2many** | Separate bridge table with composite PK | `customers__child_ids.csv` |
| **False** values | Converted to NULL | `phone: NULL` |

## Schema Metadata Files

The extractor automatically generates **metadata files** for each model to help you understand field types, relationships, and build SQL joins between tables.

### What Are Metadata Files?

For each extracted model, a metadata file is created with the naming pattern `metadata__{table_name}.csv`. These files document:

- **Field names** and their Odoo types (char, integer, many2one, many2many, etc.)
- **Relationship targets** (which model a field relates to)
- **Table locations** (main table vs. relationship tables)
- **Join columns** (for building SQL joins)

Metadata files are created even if no records were extracted, so you always have schema documentation.

### Metadata File Format

**Columns:**
- `field_name` - The field name in Odoo
- `field_type` - Odoo field type (char, integer, many2one, many2many, one2many, etc.)
- `target_model` - For relationship fields, the target Odoo model
- `location` - Which CSV file contains this field
- `source_column` - Column name to use in JOIN ON clause (if applicable)
- `target_column` - Target column name in relationship table (if applicable)

### Example: `metadata__customers.csv`

```csv
field_name,field_type,target_model,location,source_column,target_column
id,integer,,customers.csv,,
name,char,,customers.csv,,
email,char,,customers.csv,,
country_id,many2one,res.country,customers.csv,country_id_id,
country_id_id,integer,,customers.csv,,
country_id_name,char,,customers.csv,,
category_id,many2many,res.partner.category,customers__category_id.csv,partner_id,category_id
child_ids,one2many,res.partner,customers__child_ids.csv,partner_id,child_id
```

### Using Metadata for SQL Joins

The metadata file shows you exactly how to join tables:

**Example 1: Join partner with country (many2one)**
```sql
SELECT 
  p.id,
  p.name,
  p.country_id_id,
  c.name AS country_name
FROM customers p
LEFT JOIN res_country c 
  ON p.country_id_id = c.id
```

**Example 2: Join partner with categories (many2many)**
```sql
SELECT 
  p.id,
  p.name,
  cat.name AS category_name
FROM customers p
JOIN customers__category_id rel 
  ON p.id = rel.partner_id
JOIN res_partner_category cat 
  ON rel.category_id = cat.id
```

**Example 3: Find partners with child contacts (one2many)**
```sql
SELECT 
  parent.name AS parent_name,
  child.name AS child_name
FROM customers parent
JOIN customers__child_ids rel 
  ON parent.id = rel.partner_id
JOIN customers child 
  ON rel.child_id = child.id
```

### Reading Metadata in Your Transformation

The metadata file columns tell you everything you need:

- **Scalar fields** (`field_type` = char, integer, date, etc.)
  - Located in main table
  - Empty `source_column` and `target_column`
  
- **many2one fields** (flattened)
  - Original field row shows `target_model` and `source_column` for joining
  - Two additional rows for `{field}_id` and `{field}_name` columns
  
- **many2many/one2many fields** (normalized)
  - `location` shows relationship table name
  - `source_column` = foreign key to main table (e.g., `partner_id`)
  - `target_column` = foreign key to related records (e.g., `category_id`)

### Metadata Files Are Always Created

- ✅ Created for every extraction, even if no records found
- ✅ Documents the complete schema based on Odoo field metadata
- ✅ Includes only fields you selected (if using field picker)
- ✅ Includes all fields if no field selection (extract all)
- ✅ Prefixed with `metadata__` for easy identification

## Incremental Loading

Enable incremental loading to efficiently extract only new records since the last run.

### How It Works

1. **Cursor-Based Pagination** - Uses `id > cursor_id` domain filter (not offset-based)
2. **State Tracking** - Stores last processed ID after each successful run
3. **Automatic Resume** - Next run continues from last processed ID
4. **Per-Row State** - Each configuration row tracks its own state independently
5. **Full Load Override** - Switching from incremental to full load starts fresh

### State Structure

Each configuration row maintains its own state file:

```json
{
  "last_id": 1234,
  "last_run": "2026-01-27T10:30:00Z",
  "metadata": {
    "model": "res.partner",
    "incremental": true,
    "domain": [["active", "=", true]],
    "fields": ["id", "name", "email"],
    "page_size": 1000
  }
}
```

**State Fields:**
- `last_id` - Last successfully processed record ID (cursor position)
- `last_run` - ISO timestamp of last successful extraction
- `metadata` - Configuration snapshot for validation (detects domain/field changes)

### Cursor-Based Pagination

The component uses efficient cursor-based pagination:

```python
# Page 1: Extract records 1-1000
domain: [["id", ">", 0]]

# Page 2: Extract records 1001-2000
domain: [["id", ">", 1000]]

# Page 3: Extract records 2001-3000
domain: [["id", ">", 2000]]
```

**Benefits:**
- ✅ Constant query performance (no OFFSET overhead)
- ✅ Works with incremental mode (adds to existing domain)
- ✅ Handles large datasets efficiently
- ✅ Configurable page size (default: 1000)

### Incremental Mode Validation

The component validates state consistency:

- ✅ **Domain change detection** - Warns if domain filter changed
- ✅ **Field change detection** - Warns if field selection changed
- ✅ **Model validation** - Ensures state matches current configuration
- ⚠️ **State invalidation** - Changing domain/fields may require full reload

### Empty Table Handling

When no records are extracted:

- ✅ **No CSV files written** - Prevents unnecessary storage operations
- ✅ **Metadata still created** - Schema documentation always available
- ✅ **State still updated** - Tracks last_run timestamp
- ✅ **Logs warning** - Clearly indicates no data found

## Development

### Run Locally

```bash
# Set up environment
export KBC_DATADIR=/path/to/data/dir

# Run component
python src/component.py
```

### Docker

```bash
# Build
docker build -t odoo-extractor .

# Run
docker run -v $(pwd)/data:/data odoo-extractor
```

### Code Quality

This component follows Keboola code quality standards:

```bash
# Format code
uvx ruff format .

# Check linting
uvx ruff check --fix .
```

**Quality Features:**
- ✅ Modern Python 3.13 type hints (`list[str]`, `dict[str, Any]`, `int | None`)
- ✅ No deprecated typing imports (`typing.List`, `typing.Dict`, `typing.Optional`)
- ✅ `@staticmethod` decorators on pure functions
- ✅ `@sync_action` decorators for UI actions
- ✅ Dataclass-driven architecture (`BridgeTableMetadata`, `SplitTablesResult`)
- ✅ Ruff formatted and linted
- ✅ Clean orchestrator pattern in `run()` method

## Architecture

### Core Modules

**`clients/xmlrpc_client.py`** - XML-RPC protocol client (universal compatibility)
  - `authenticate()` - Odoo authentication via common service
  - `search_read()` - Extract data with domain filtering
  - `get_fields()` - Get field definitions for a model
  - `list_models()` - Discover available models
  - `list_databases()` - Discover available databases
  - `test_connection()` - Validate credentials

**`clients/json2_client.py`** - JSON-2 protocol client (Odoo 19+, high performance)
  - Same interface as XmlRpcClient
  - 2-3x faster than XML-RPC
  - No username required (API key only)
  - Native JSON payloads

**`configuration.py`** - Pydantic models for validation
  - `Parameters` - Global connection parameters
  - `RowConfiguration` - Per-row extraction configuration
  - URL validation, field validation, encrypted #api_key support

**`component.py`** - Main component with extraction logic
  - `run()` - Clean orchestrator (load state → extract → write state)
  - `_extract_data()` - Per-model extraction with cursor-based pagination
  - `_split_records()` - Smart relational field handling (returns `SplitTablesResult`)
  - `_write_csv()` - CSV generation with proper escaping
  - `_write_metadata()` - Schema documentation generation
  - **Sync Actions:**
    - `test_connection_action()` - Test credentials (@sync_action)
    - `list_databases_action()` - Load databases for dropdown (@sync_action)
    - `list_models_action()` - Load models for dropdown (@sync_action)
    - `list_fields_action()` - Load fields for multi-select (@sync_action)

### Patterns Used

- **Configuration Rows Pattern**: One row = one model (modern Keboola standard)
- **Client Abstraction**: Protocol-agnostic interface (XmlRpcClient + Json2Client)
- **Orchestrator Pattern**: `run()` delegates to well-named methods
- **Cursor-Based Pagination**: `id > cursor_id` for efficient large dataset handling
- **Load-Once/Write-Once**: State loaded at start, written at end
- **Sync Actions**: Dynamic UI with @sync_action decorator
- **Type Safety**: Full type hints throughout (Python 3.13)
- **Dataclass Architecture**: `BridgeTableMetadata`, `SplitTablesResult` for type-safe structures

## Tested Against

- **Odoo Versions**: 18.0, 19.0
- **Python Version**: 3.13
- **Protocols**: XML-RPC (universal), JSON-2 (Odoo 19+)
- **Test Records**: 40+ partners, 20+ relationship records
- **Incremental Runs**: Verified across multiple runs with state persistence

## License

MIT License

## Author

Keboola
