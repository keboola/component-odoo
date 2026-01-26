"""
Odoo XML-RPC API Client

Handles authentication and data extraction from Odoo ERP via XML-RPC.
Uses modern Python 3.9+ type hints with built-in generics.
"""

import logging
import xmlrpc.client
from typing import Any

from keboola.component.exceptions import UserException


class XmlRpcClient:
    """Client for interacting with Odoo XML-RPC API."""

    def __init__(self, url: str, database: str, username: str | None, api_key: str) -> None:
        """
        Initialize Odoo client.

        Args:
            url: Odoo instance URL (e.g., https://mycompany.odoo.com)
            database: Database name
            username: User email/login
            api_key: API key or password
        """
        self.url: str = url.rstrip("/")
        self.database: str = database
        self.username: str | None = username
        self.api_key: str = api_key
        self.uid: int | None = None

        # Initialize XML-RPC endpoints
        self.common: xmlrpc.client.ServerProxy = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self.models: xmlrpc.client.ServerProxy = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")
        self.db: xmlrpc.client.ServerProxy = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/db")

        logging.info(f"Initialized Odoo client for {self.url}")

    def authenticate(self) -> int:
        """
        Authenticate with Odoo and get user ID.

        Returns:
            User ID

        Raises:
            UserException: If authentication fails
        """
        try:
            uid = self.common.authenticate(self.database, self.username, self.api_key, {})

            if not uid or not isinstance(uid, int):
                raise UserException("Authentication failed. Please check your credentials.")

            self.uid = uid
            logging.info(f"Successfully authenticated as user ID: {self.uid}")
            return self.uid

        except xmlrpc.client.Fault as e:
            raise UserException(f"Odoo authentication error: {e.faultString}")
        except Exception as e:
            raise UserException(f"Failed to connect to Odoo: {str(e)}")

    def search_read(
        self,
        model: str,
        domain: list[Any] | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search and read records from Odoo model.

        Args:
            model: Odoo model name (e.g., 'res.partner', 'sale.order')
            domain: Search domain filter
            fields: List of fields to retrieve
            limit: Maximum number of records
            offset: Number of records to skip
            order: Sort order

        Returns:
            List of records as dictionaries

        Raises:
            UserException: If API call fails
        """
        if not self.uid:
            self.authenticate()

        domain = domain or []

        try:
            kwargs: dict[str, Any] = {
                "fields": fields or [],
                "offset": offset,
            }

            if limit:
                kwargs["limit"] = limit
            if order:
                kwargs["order"] = order

            result = self.models.execute_kw(
                self.database,
                self.uid,
                self.api_key,
                model,
                "search_read",
                [domain],
                kwargs,
            )

            # Ensure we got a list back
            if not isinstance(result, list):
                raise UserException(f"Unexpected response type from Odoo: {type(result)}")

            records: list[dict[str, Any]] = result
            logging.info(f"Retrieved {len(records)} records from {model}")
            return records

        except xmlrpc.client.Fault as e:
            raise UserException(f"Odoo API error: {e.faultString}")
        except Exception as e:
            raise UserException(f"Failed to fetch data from {model}: {str(e)}")

    def get_model_fields(self, model: str) -> dict[str, dict[str, Any]]:
        """
        Get field definitions for an Odoo model.

        Args:
            model: Odoo model name

        Returns:
            Dictionary of field definitions

        Raises:
            UserException: If API call fails
        """
        if not self.uid:
            self.authenticate()

        try:
            result = self.models.execute_kw(
                self.database,
                self.uid,
                self.api_key,
                model,
                "fields_get",
                [],
                {
                    "attributes": [
                        "string",
                        "type",
                        "help",
                        "required",
                        "relation",
                        "relation_field",
                    ]
                },
            )

            if not isinstance(result, dict):
                raise UserException(f"Unexpected response type from Odoo: {type(result)}")

            fields: dict[str, dict[str, Any]] = result
            logging.info(f"Retrieved field definitions for {model}")
            return fields

        except xmlrpc.client.Fault as e:
            raise UserException(f"Odoo API error: {e.faultString}")
        except Exception as e:
            raise UserException(f"Failed to get fields for {model}: {str(e)}")

    def list_models(self) -> list[dict[str, Any]]:
        """
        List all available Odoo models.

        Returns:
            List of model dictionaries with 'model' and 'name' keys

        Raises:
            UserException: If API call fails
        """
        if not self.uid:
            self.authenticate()

        try:
            result = self.models.execute_kw(
                self.database,
                self.uid,
                self.api_key,
                "ir.model",
                "search_read",
                [
                    [
                        (
                            "transient",
                            "=",
                            False,
                        ),  # Filter out wizards/temporary models
                        ("model", "!=", "_unknown"),  # Filter out placeholder model
                    ]
                ],
                {"fields": ["model", "name"], "order": "name asc"},
            )

            if not isinstance(result, list):
                raise UserException(f"Unexpected response type from Odoo: {type(result)}")

            models: list[dict[str, Any]] = result
            logging.info(f"Retrieved {len(models)} Odoo models")
            return models

        except xmlrpc.client.Fault as e:
            raise UserException(f"Odoo API error: {e.faultString}")
        except Exception as e:
            raise UserException(f"Failed to list models: {str(e)}")

    def get_version(self) -> str:
        """
        Get Odoo version (no authentication required).

        Returns:
            Version string (e.g., "18.0", "19.0")

        Raises:
            UserException: If version check fails
        """
        try:
            version_info = self.common.version()

            if isinstance(version_info, dict):
                version = version_info.get("server_version", "unknown")
            else:
                version = "unknown"

            logging.info(f"Detected Odoo version: {version} via XML-RPC")
            return version

        except xmlrpc.client.Fault as e:
            raise UserException(f"XML-RPC version check failed: {e.faultString}")
        except Exception as e:
            raise UserException(f"XML-RPC version check failed: {str(e)}")

    def test_connection(self) -> dict[str, str]:
        """
        Test connection and authentication.

        Returns:
            Dict with version and protocol info

        Raises:
            UserException: If connection fails
        """
        if not self.database:
            raise UserException("Database name is required")

        if not self.username:
            raise UserException("Username is required for XML-RPC authentication")

        if not self.api_key:
            raise UserException("API key is required")

        try:
            version = self.get_version()
            self.authenticate()

            return {"version": version, "protocol": "XML-RPC"}

        except UserException as e:
            raise e
        except Exception as e:
            raise UserException(f"XML-RPC connection failed: {str(e)}")

    def list_databases(self) -> list[str]:
        """
        List available databases on the Odoo instance.

        Returns:
            List of database names

        Raises:
            UserException: If listing databases fails
        """
        try:
            databases = self.db.list()

            if not isinstance(databases, list):
                raise UserException(f"Unexpected response type from Odoo: {type(databases)}")

            logging.info(f"Retrieved {len(databases)} database(s) via XML-RPC")
            return databases

        except xmlrpc.client.Fault as e:
            raise UserException(f"XML-RPC error listing databases: {e.faultString}")
        except Exception as e:
            raise UserException(f"Failed to list databases: {str(e)}")
