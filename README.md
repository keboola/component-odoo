# Odoo Extractor

Extract data from Odoo ERP via XML-RPC API with dynamic model/field discovery and modern Python 3.13 implementation.

## Features

### Core Capabilities
- ✅ **Dynamic Model Discovery** - Browse and select from 146+ Odoo models via UI
- ✅ **Field Discovery** - Automatically load field definitions for selected models
- ✅ **Test Connection** - Validate credentials before running extractions
- ✅ **Multiple Endpoints** - Extract data from multiple models in one run
- ✅ **Incremental Loading** - ID-based state tracking for efficient updates
- ✅ **Auto-Flattening** - Handles many2one, many2many relationships automatically

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

## Data Flattening

The extractor automatically flattens Odoo's nested data structures:

- **Many2one fields** (e.g., `country_id: [21, "United States"]`) →  
  Creates two columns: `country_id_id` and `country_id_name`
  
- **Many2many/One2many fields** (e.g., `tag_ids: [1, 5, 9]`) →  
  Comma-separated string: `"1,5,9"`
  
- **False values** → Converted to `NULL`

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
  - `_flatten_record()` - Odoo data flattening (@staticmethod)
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
