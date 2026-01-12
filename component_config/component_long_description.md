# Odoo Extractor

Extract data from Odoo ERP systems via XML-RPC API with intelligent model/field discovery and incremental loading.

## Key Features

### Dynamic UI Experience
- **Test Connection** - Validate Odoo credentials before running extractions
- **Model Discovery** - Browse and select from 146+ Odoo models automatically
- **Field Discovery** - Load field definitions dynamically based on selected model
- **No Manual Entry** - All models and fields discovered from your Odoo instance

### Powerful Data Extraction
- **Multiple Endpoints** - Configure multiple models in a single extraction
- **Incremental Loading** - ID-based state tracking for efficient updates
- **Auto-Flattening** - Handles Odoo many2one and many2many relationships
- **Flexible Filtering** - Use Odoo domain filters for targeted extraction

### Production-Ready
- **State Management** - Reliable tracking across all endpoints with nested structure
- **Modern Python 3.13** - Full type safety with modern type hints
- **Quality Standards** - Ruff formatted, lint-free, proper error handling
- **Well-Tested** - Verified against Odoo 19.0 with 40+ test records

## Common Use Cases

- **Customer Data**: Extract contacts, companies, addresses from `res.partner`
- **Sales Orders**: Pull sales data from `sale.order` and `sale.order.line`
- **Invoicing**: Extract invoices from `account.move` and `account.move.line`
- **Product Catalogs**: Get products from `product.product` and `product.template`
- **Inventory**: Track stock movements via `stock.move`
- **CRM**: Extract leads and opportunities from `crm.lead`
- **Custom Modules**: Access any custom Odoo model

## How It Works

1. **Connect**: Enter your Odoo URL, database, and credentials
2. **Test**: Click "Test Connection" to validate access
3. **Select Models**: Choose models from the dynamic dropdown (146+ available)
4. **Pick Fields**: Select specific fields or extract all
5. **Configure**: Set incremental loading, limits, and sort order
6. **Extract**: Run extraction and get clean CSV output

## Technical Highlights

- **Sync Actions**: Real-time model and field loading via Keboola sync actions
- **Nested State**: Clean state structure with `state["endpoints"][table]["last_id"]`
- **Type Safety**: Full Python 3.13 type hints throughout
- **API Discovery**: Uses `ir.model` and `fields_get()` for metadata
- **Error Handling**: Clear UserException messages for all failure scenarios

Perfect for integrating Odoo data into your data warehouse or analytics platform!
