"""
Shared Odoo component base — constants, helpers, and sync action mixin.

Provides everything that is identical between the extractor and writer:
- Protocol constants and display names
- Client factory
- Error message formatting
- Database discovery (with proper /web/database/list support for Odoo SaaS)
- Sync action implementations (testConnection, listModels, listFields, listDatabases)
"""

import logging
from urllib.parse import urlparse

from keboola.component.base import sync_action
from keboola.component.exceptions import UserException
from keboola.component.sync_actions import SelectElement

from shared.clients.json2_client import Json2Client
from shared.clients.xmlrpc_client import XmlRpcClient
from shared.connection import PROTOCOL_JSON2

DISPLAY_JSON2 = "JSON-2"
DISPLAY_XMLRPC = "XML-RPC"


def initialize_client(config) -> XmlRpcClient | Json2Client:
    """
    Initialize and return the appropriate Odoo client based on api_protocol config.

    Args:
        config: OdooConnectionConfig (or any subclass) with odoo_url, database,
                username, api_key, api_protocol fields.

    Returns:
        Initialized Json2Client or XmlRpcClient.
    """
    ClientClass = Json2Client if config.api_protocol == PROTOCOL_JSON2 else XmlRpcClient
    return ClientClass(
        url=config.odoo_url,
        database=config.database,
        username=config.username,
        api_key=config.api_key,
    )


def extract_short_error(exception: Exception) -> str:
    """
    Extract a concise, user-friendly error message from an exception.

    Maps common Odoo/HTTP error patterns to readable descriptions.
    For authentication failures, extracts the specific reason from the
    full error string (e.g. the last line of a server-side traceback).
    """
    error_str = str(exception)

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
        parts = error_str.split(":")
        if len(parts) > 1:
            return parts[-1].strip()
        return error_str
    else:
        return error_str


def discover_databases(url: str) -> list[str]:
    """
    Discover available databases on an Odoo instance.

    Strategy (in order):
    1. POST to /web/database/list — works on Odoo SaaS and most self-hosted instances.
       This is the only endpoint that returns the real DB name on Odoo SaaS
       (xmlrpc/2/db returns Access Denied there).
    2. Fall back to xmlrpc/2/db list() — for self-hosted instances that may not
       expose /web/database/list.
    3. For .odoo.com instances, fall back to a subdomain-derived guess as a last resort,
       clearly labelled so the user knows it may not be exact.

    Args:
        url: Odoo instance URL (e.g. https://mycompany.odoo.com)

    Returns:
        List of database name strings.

    Raises:
        UserException: If all strategies fail and no fallback is available.
    """
    # Strategy 1: /web/database/list (JSON-RPC POST, no auth required)
    try:
        client = Json2Client(url, "", None, "")
        databases = client.list_databases()
        logging.info(f"Found {len(databases)} database(s) via /web/database/list: {databases}")
        return databases
    except Exception as e:
        logging.debug(f"/web/database/list failed: {e}")

    # Strategy 2: xmlrpc/2/db list()
    try:
        client = XmlRpcClient(url, "", "", "")
        databases = client.list_databases()
        logging.info(f"Found {len(databases)} database(s) via XML-RPC db.list(): {databases}")
        return databases
    except Exception as e:
        logging.debug(f"XML-RPC db.list() failed: {e}")

    # Strategy 3: subdomain guess for .odoo.com instances
    if ".odoo.com" in url.lower():
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        subdomain = hostname.replace(".odoo.com", "").replace(".dev", "").replace(".saas", "")
        if subdomain:
            logging.warning(f"Could not query database list — falling back to subdomain guess: {subdomain}")
            return [subdomain]

    raise UserException(
        "Could not retrieve the database list from this Odoo instance. Please enter the database name manually."
    )


class OdooSyncActionsMixin:
    """
    Mixin providing shared sync action implementations for Odoo components.

    Expects the inheriting class to have:
      - self.config  — OdooConnectionConfig (or subclass) with odoo_url, database,
                       username, api_key, api_protocol, model fields
      - self.client  — XmlRpcClient | Json2Client (initialized via initialize_client())
    """

    @sync_action("testConnection")
    def test_connection_action(self) -> dict[str, str]:
        """
        Test connection showing Odoo version, protocol availability, and auth status.

        Message format:
        "Odoo {version}. Supports: JSON-2 {✓/✗}, XML-RPC {✓/✗}. {auth result}, {N} models"
        """
        try:
            odoo_url = self.config.odoo_url
            database = self.config.database
            username = self.config.username
            api_key = self.config.api_key
            selected_protocol = self.config.api_protocol

            xmlrpc_client = XmlRpcClient(odoo_url, database, username, api_key)
            json2_client = Json2Client(odoo_url, database, username, api_key)

            # Step 1: Check protocol availability (no auth required)
            protocols_available = {}
            odoo_version = None

            try:
                odoo_version = xmlrpc_client.get_version()
                protocols_available[DISPLAY_XMLRPC] = True
            except Exception as e:
                protocols_available[DISPLAY_XMLRPC] = False
                logging.debug(f"XML-RPC availability check failed: {e}")

            try:
                version = json2_client.get_version()
                protocols_available[DISPLAY_JSON2] = True
                if not odoo_version:
                    odoo_version = version
            except Exception as e:
                protocols_available[DISPLAY_JSON2] = False
                logging.debug(f"JSON-2 availability check failed: {e}")

            if not odoo_version:
                raise UserException("Cannot connect to Odoo instance at this URL")

            # Step 2: Build supports string
            supports_parts = []
            for protocol in [DISPLAY_JSON2, DISPLAY_XMLRPC]:
                symbol = "✓" if protocols_available.get(protocol, False) else "✗"
                supports_parts.append(f"{protocol} {symbol}")
            supports_str = ", ".join(supports_parts)

            # Step 3: Test authentication for the selected protocol
            selected_client: XmlRpcClient | Json2Client | None = None
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
                    return {
                        "status": "error",
                        "message": (
                            f"Odoo {odoo_version}. Supports: {supports_str}. "
                            f"Authentication failed using {DISPLAY_JSON2} ({extract_short_error(e)})"
                        ),
                    }
            else:
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
                    return {
                        "status": "error",
                        "message": (
                            f"Odoo {odoo_version}. Supports: {supports_str}. "
                            f"Authentication failed using {DISPLAY_XMLRPC} ({extract_short_error(e)})"
                        ),
                    }

            # Step 4: Get model count
            model_suffix = ""
            try:
                models = selected_client.list_models()
                model_suffix = f", {len(models)} models"
            except Exception as e:
                logging.warning(f"Could not fetch model count: {e}")

            return {
                "status": "success",
                "message": f"Odoo {odoo_version}. Supports: {supports_str}. {auth_message}{model_suffix}",
            }

        except UserException:
            raise
        except Exception as e:
            raise UserException(f"Connection test failed: {str(e)}")

    @sync_action("listModels")
    def list_models_action(self) -> list[SelectElement]:
        """List available Odoo models for the model dropdown."""
        try:
            models = self.client.list_models()
            return [
                SelectElement(value=m["model"], label=f"{m['model']} - {m['name']}")
                for m in sorted(models, key=lambda m: m["model"])
            ]
        except UserException:
            raise
        except Exception as e:
            raise UserException(f"Failed to load models: {str(e)}")

    @sync_action("listFields")
    def list_fields_action(self) -> list[SelectElement]:
        """List fields for the selected Odoo model."""
        try:
            model = self.config.model
            if not model:
                raise UserException("Please select a model first")

            fields_dict = self.client.get_model_fields(model)
            return [
                SelectElement(
                    value=field_name,
                    label=f"{info.get('string', field_name)} ({field_name}) - {info.get('type', 'unknown')}",
                )
                for field_name, info in fields_dict.items()
                if field_name != "_unknown"
            ]
        except UserException:
            raise
        except Exception as e:
            raise UserException(f"Failed to load fields: {str(e)}")

    @sync_action("listDatabases")
    def list_databases_action(self) -> list[SelectElement]:
        """
        List available databases on the Odoo instance.

        Uses discover_databases() which tries /web/database/list first (works on
        Odoo SaaS where xmlrpc/2/db returns Access Denied), then falls back to
        XML-RPC db.list(), then to subdomain guessing for .odoo.com instances.
        """
        try:
            databases = discover_databases(self.config.odoo_url)
            return [SelectElement(value=db) for db in databases]
        except UserException:
            raise
        except Exception as e:
            raise UserException(f"Failed to list databases: {str(e)}")
