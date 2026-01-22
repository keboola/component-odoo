# Odoo Extractor

Extract data from Odoo ERP via XML-RPC API with dynamic model/field discovery and modern Python 3.13 implementation.

## Features

### Core Capabilities
- ✅ **Dynamic Model Discovery** - Browse and select from hundreds of Odoo models via UI
- ✅ **Field Discovery** - Automatically load field definitions for selected models
- ✅ **Test Connection** - Validate credentials before running extractions
- ✅ **Multiple Endpoints** - Extract data from multiple models in one run
- ✅ **Incremental Loading** - ID-based state tracking for efficient updates
- ✅ **Smart Relationship Handling** - Automatically splits many2many/one2many into normalized tables

### Technical Highlights
- ✅ **Modern Type Hints** - Python 3.13 with `list[str]`, `dict[str, Any]`, `int | None`
- ✅ **Sync Actions** - Dynamic UI with testConnection, listModels, listFields
- ✅ **Nested State Structure** - Clean `state["endpoints"][table]["last_id"]` format
- ✅ **Code Quality** - Ruff formatted, type-checked, @staticmethod decorators

## Configuration

### UI-Based Configuration (Recommended)

The extractor provides a dynamic UI with:

1. **Connection Section**
   - Odoo URL, Database, Username, API Key
   - **Test Connection** button to validate credentials

2. **Endpoints Configuration**
   - **Model Dropdown**: Select from 146+ models (autoloads from your Odoo)
   - **Fields Multi-Select**: Choose fields to extract (autoloads based on model)
   - **Output Table Name**: e.g., `customers.csv`
   - **Incremental Loading**: Toggle for ID-based incremental extraction
   - **Record Limit**: Default 1000 (0 = no limit)
   - **Sort Order**: Default `id asc`

3. **No Manual Entry Required**
   - Models discovered dynamically from `ir.model`
   - Fields discovered from `fields_get()` API
   - Shows field labels, types, and technical names

### JSON Configuration (Advanced)

You can also configure via JSON (for automation or advanced use cases):

#### Connection Parameters
- `odoo_url` - Odoo instance URL
- `database` - Database name
- `username` - User email/login
- `#api_key` - API key or password (encrypted)

#### Endpoints
- `model` - Odoo model name (from dropdown or manual)
- `output_table` - Output CSV filename (e.g., `partners.csv`)
- `fields` - Field list (empty = extract all)
- `domain` - Odoo domain filter (advanced)
- `limit` - Max records (default: 1000)
- `order` - Sort order (default: `id asc`)
- `incremental` - Enable incremental (default: false)
- `primary_key` - Primary key (default: `["id"]`)

## Example Configuration

```json
{
  "parameters": {
    "odoo_url": "https://demo.odoo.com",
    "database": "demo",
    "username": "admin",
    "api_key": "admin",
    "endpoints": [
      {
        "model": "res.partner",
        "output_table": "partners.csv",
        "fields": ["id", "name", "email", "phone", "country_id"],
        "limit": 1000,
        "incremental": false,
        "primary_key": ["id"]
      },
      {
        "model": "sale.order",
        "output_table": "sales.csv",
        "domain": [["state", "=", "sale"]],
        "incremental": true,
        "primary_key": ["id"]
      }
    ]
  }
}
```

## Supported Models

Extract from any Odoo model:

- **Contacts**: `res.partner`, `res.users`
- **Sales**: `sale.order`, `sale.order.line`
- **Invoicing**: `account.move`, `account.move.line`
- **Inventory**: `product.product`, `product.template`, `stock.move`
- **CRM**: `crm.lead`, `crm.stage`
- And many more!

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

**`res_partner.csv`** (main table):
```csv
id,name
15,Azure Interior
```

**`res_partner__category_id.csv`** (relationship table):
```csv
partner_id,category_id
15,5
```

**`res_partner__child_ids.csv`** (relationship table):
```csv
partner_id,child_id
15,27
15,34
15,28
```

### Why Auto-Split?

✅ **Proper relational structure** - Industry-standard data modeling
✅ **Easy SQL joins** - `JOIN res_partner__category_id ON id = partner_id`
✅ **BI tool friendly** - Works seamlessly with Tableau, PowerBI, Looker
✅ **No data loss** - Preserves all relationship information
✅ **Scalable** - Handles large many2many datasets efficiently

### Field Type Summary

| Odoo Field Type | Storage Strategy | Example Output |
|-----------------|------------------|----------------|
| **Scalar** (text, number, date) | Main table column | `email: "user@example.com"` |
| **many2one** | Flattened in main table | `country_id_id: 233`<br>`country_id_name: "United States"` |
| **many2many** | Separate relationship table | `res_partner__category_id.csv` |
| **one2many** | Separate relationship table | `res_partner__child_ids.csv` |
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

### Example: `metadata__res_partner.csv`

```csv
field_name,field_type,target_model,location,source_column,target_column
id,integer,,res_partner.csv,,
name,char,,res_partner.csv,,
email,char,,res_partner.csv,,
country_id,many2one,res.country,res_partner.csv,country_id_id,
country_id_id,integer,,res_partner.csv,,
country_id_name,char,,res_partner.csv,,
category_id,many2many,res.partner.category,res_partner__category_id.csv,partner_id,category_id
child_ids,one2many,res.partner,res_partner__child_ids.csv,partner_id,child_id
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
FROM res_partner p
LEFT JOIN res_country c 
  ON p.country_id_id = c.id
```

**Example 2: Join partner with categories (many2many)**
```sql
SELECT 
  p.id,
  p.name,
  cat.name AS category_name
FROM res_partner p
JOIN res_partner__category_id rel 
  ON p.id = rel.partner_id
JOIN res_partner_category cat 
  ON rel.category_id = cat.id
```

**Example 3: Find partners with child contacts (one2many)**
```sql
SELECT 
  parent.name AS parent_name,
  child.name AS child_name
FROM res_partner parent
JOIN res_partner__child_ids rel 
  ON parent.id = rel.partner_id
JOIN res_partner child 
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

Enable incremental loading to track the last extracted record ID per endpoint:

**State Structure:**
```json
{
  "endpoints": {
    "partners.csv": {"last_id": 23},
    "companies.csv": {"last_id": 11}
  }
}
```

**How it Works:**
1. First run extracts all records
2. Stores `last_id` in nested state structure
3. Subsequent runs only fetch records with `id > last_id`
4. Each endpoint tracks its state independently
5. State written atomically (all endpoints at once)

## Development

### Run Locally

```bash
# Run with local config
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
- ✅ Ruff formatted and linted
- ✅ Clean orchestrator pattern in `run()` method (~15 lines)

## Architecture

### Core Modules
- **`odoo_client.py`** - XML-RPC client with authentication, data fetching, and metadata discovery
  - `authenticate()` - Odoo authentication
  - `search_read()` - Extract data from models
  - `get_model_fields()` - Get field definitions
  - `list_models()` - Discover available models (for UI)
  - `test_connection()` - Validate credentials

- **`configuration.py`** - Pydantic models for validation
  - `Configuration` - Main config with encrypted #api_key support
  - `OdooEndpoint` - Per-endpoint settings
  - URL validation, endpoint validation

- **`component.py`** - Main component with extraction logic
  - `run()` - Clean orchestrator (load state → extract → write state)
  - `_extract_endpoint()` - Per-model extraction logic
  - `_split_records()` - Smart relational field handling (@staticmethod)
  - `_write_csv()` - CSV generation (@staticmethod)
  - **Sync Actions:**
    - `test_connection_action()` - Test credentials (@sync_action)
    - `list_models_action()` - Load models for dropdown (@sync_action)
    - `list_fields_action()` - Load fields for dropdown (@sync_action)

### Patterns Used
- **Orchestrator Pattern**: `run()` delegates to well-named methods
- **Load-Once/Write-Once**: State loaded at start, written at end
- **Nested State**: `state["endpoints"][table]["last_id"]` structure
- **Sync Actions**: Dynamic UI with @sync_action decorator
- **Type Safety**: Full type hints throughout (Python 3.13)

## Tested Against

- **Odoo Version**: 19.0-20251208
- **Python Version**: 3.13
- **Test Records**: 40+ partners, 20+ companies
- **Incremental Runs**: Verified across multiple runs

## License

MIT License

## Author

Keboola
