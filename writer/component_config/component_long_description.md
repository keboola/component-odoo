# Odoo Writer

Write data from Keboola Storage into Odoo ERP via XML-RPC or JSON-2 API. Maps CSV columns directly to Odoo field names and creates records in any configured model.

## Key Features

### Dynamic UI Experience
- **Test Connection** - Validate Odoo credentials before running
- **Model Discovery** - Browse and select from 146+ Odoo models automatically
- **Field Discovery** - Load field definitions to know the expected column names
- **No Manual Mapping** - CSV columns map directly to Odoo field names

### Flexible Data Writing
- **Any Model** - Write to any Odoo model: contacts, products, orders, custom models
- **Batch Processing** - Configurable batch size for efficient bulk creates
- **Smart Defaults** - Empty CSV values are omitted, letting Odoo apply field defaults
- **Protocol Choice** - Use XML-RPC (all versions) or JSON-2 (Odoo 19+)

### Production-Ready
- **Fail Fast** - Clear error reporting with batch number and record range on failure
- **Modern Python 3.13** - Full type safety with modern type hints
- **Quality Standards** - Ruff formatted, lint-free, proper error handling
- **Well-Tested** - Verified against Odoo 19.0

## Common Use Cases

- **Import Contacts**: Create new partners in `res.partner` from a CRM export
- **Sync Products**: Push product catalog changes to `product.product`
- **Load Orders**: Create sales orders in `sale.order` from an external system
- **Populate Custom Models**: Write records into any custom Odoo module
- **Data Migration**: Bulk-create records during an Odoo migration project

## How It Works

1. **Connect**: Enter your Odoo URL, database, and credentials
2. **Test**: Click "Test Connection" to validate access
3. **Select Model**: Choose the target model from the dynamic dropdown
4. **Check Fields**: Use "List Fields" to see available field names
5. **Prepare Data**: Name your CSV columns to match Odoo field names
6. **Write**: Run the component — records are created in Odoo immediately

## Column Mapping

CSV column names map directly to Odoo field names — no explicit mapping required:

| CSV column | Odoo field |
|------------|------------|
| `name` | `name` |
| `email` | `email` |
| `phone` | `phone` |

Use the **List Fields** sync action to discover the exact field names for your target model.

## Technical Highlights

- **Sync Actions**: Real-time model and field loading via Keboola sync actions
- **Batch Creates**: Single `create()` API call per batch for efficiency
- **ID Column Ignored**: Any `id` column in the CSV is silently skipped (Odoo assigns IDs)
- **Type Safety**: Full Python 3.13 type hints throughout
- **Error Handling**: Clear UserException messages for all failure scenarios

Perfect for pushing data from your data warehouse or external systems into Odoo!
