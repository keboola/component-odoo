"""
Odoo JSON-2 API Client

Handles authentication and data extraction from Odoo ERP via JSON-2 API.
Compatible with Odoo v19+.
"""

import logging
from typing import Any

from keboola.component.exceptions import UserException
from keboola.http_client import HttpClient


class Json2Client:
    """Client for interacting with Odoo JSON-2 API (Odoo 19+)."""

    def __init__(self, url: str, database: str, username: str | None, api_key: str) -> None:
        """
        Initialize Odoo JSON-2 client.

        Args:
            url: Odoo instance URL (e.g., https://mycompany.odoo.com)
            database: Database name
            username: User email/login (not used in JSON-2 auth)
            api_key: API key (bearer token)
        """
        self.url: str = url.rstrip("/")
        self.database: str = database
        self.username: str | None = username  # Not used in JSON-2 auth
        self.api_key: str = api_key

        # Prepare default headers
        default_header = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "keboola-odoo-extractor/1.0",
        }

        # Add database header if specified
        if self.database:
            default_header["X-Odoo-Database"] = self.database

        # Initialize HTTP client
        self.http_client = HttpClient(
            base_url=f"{url.rstrip('/')}/json/2",
            auth_header={"Authorization": f"bearer {api_key}"},
            default_http_header=default_header,
        )

        logging.info(f"Initialized Odoo JSON-2 client for {self.url}")

    def get_version(self) -> str:
        """
        Get Odoo version (no authentication required).

        Returns:
            Version string (e.g., "19.0", "20.0")

        Raises:
            UserException: If version check fails
        """
        try:
            version_info = self.http_client.get(
                endpoint_path=f"{self.url}/web/version",
                is_absolute_path=True,
                timeout=10,
            )
            version = version_info.get("version", "unknown")

            logging.info(f"Detected Odoo version: {version} via JSON-2")
            return version

        except Exception as e:
            # Check if it's an HTTP error
            if hasattr(e, "response") and hasattr(e.response, "status_code"):
                if e.response.status_code == 404:
                    raise UserException("JSON-2 version check failed: HTTP 404 - /web/version endpoint not found")
                else:
                    raise UserException(f"JSON-2 version check failed: HTTP {e.response.status_code}")
            raise UserException(f"JSON-2 version check failed: {str(e)}")

    def test_connection(self) -> dict[str, str]:
        """
        Test connection and authentication.

        Returns:
            Dict with version and protocol info

        Raises:
            UserException: If connection fails
        """
        try:
            # Get version (no auth required)
            version = self.get_version()

            # Test authentication with a minimal authenticated call
            # Try to call /json/2/res.users/search_read with domain and limit
            _ = self.http_client.post(
                endpoint_path="res.users/search_read",
                json={"domain": [], "limit": 1, "fields": ["id"]},
                timeout=10,
            )

            # If we got here, authentication worked
            logging.info("JSON-2 authentication successful")
            return {"version": version, "protocol": "JSON-2"}

        except Exception as e:
            # Check if it's an HTTP error
            if hasattr(e, "response") and hasattr(e.response, "status_code"):
                if e.response.status_code == 401:
                    raise UserException("JSON-2 authentication failed: Invalid API key")
                elif e.response.status_code == 403:
                    raise UserException("JSON-2 authentication failed: Access forbidden")
                elif e.response.status_code == 404:
                    raise UserException("JSON-2 API not available (HTTP 404) - Odoo instance may be older than v19")
                else:
                    raise UserException(f"JSON-2 connection failed: HTTP {e.response.status_code}")
            if isinstance(e, UserException):
                raise e
            raise UserException(f"JSON-2 connection failed: {str(e)}")

    def list_models(self) -> list[dict[str, str]]:
        """
        List available Odoo models.

        Returns:
            List of model dictionaries with 'model' and 'name' keys

        Raises:
            UserException: If listing models fails
        """
        try:
            models = self.http_client.post(
                endpoint_path="ir.model/search_read",
                json={
                    "domain": [
                        (
                            "transient",
                            "=",
                            False,
                        ),  # Filter out wizards/temporary models
                        ("model", "!=", "_unknown"),  # Filter out placeholder model
                    ],
                    "fields": ["model", "name"],
                },
                timeout=30,
            )
            logging.info(f"Retrieved {len(models)} models via JSON-2")
            return models

        except Exception as e:
            # Check if it's an HTTP error
            if hasattr(e, "response") and hasattr(e.response, "status_code"):
                if e.response.status_code == 401:
                    raise UserException("JSON-2 authentication failed: Invalid API key")
                elif e.response.status_code == 403:
                    raise UserException("JSON-2 access forbidden: User lacks permission to list models")
                elif e.response.status_code == 404:
                    raise UserException("JSON-2 API not available (HTTP 404)")
                else:
                    raise UserException(f"JSON-2 failed to list models: HTTP {e.response.status_code}")
            if isinstance(e, UserException):
                raise e
            raise UserException(f"JSON-2 failed to list models: {str(e)}")

    def get_model_fields(self, model: str) -> dict[str, dict[str, Any]]:
        """
        Get field definitions for an Odoo model.

        Args:
            model: Odoo model name (e.g., 'res.partner')

        Returns:
            Dictionary of field definitions with field metadata

        Raises:
            UserException: If getting fields fails
        """
        try:
            fields = self.http_client.post(
                endpoint_path=f"{model}/fields_get",
                json={
                    "attributes": [
                        "string",
                        "type",
                        "help",
                        "required",
                        "relation",
                        "relation_field",
                    ]
                },
                timeout=30,
            )

            if not isinstance(fields, dict):
                raise UserException(f"Unexpected response type from Odoo: {type(fields)}")

            logging.info(f"Retrieved {len(fields)} fields for {model} via JSON-2")
            return fields

        except Exception as e:
            # Check if it's an HTTP error
            if hasattr(e, "response") and hasattr(e.response, "status_code"):
                if e.response.status_code == 401:
                    raise UserException("JSON-2 authentication failed: Invalid API key")
                elif e.response.status_code == 403:
                    raise UserException(f"JSON-2 access forbidden: User lacks permission to access {model}")
                elif e.response.status_code == 404:
                    raise UserException(f"JSON-2 model not found: {model} does not exist or API unavailable")
                else:
                    raise UserException(f"JSON-2 failed to get fields for {model}: HTTP {e.response.status_code}")
            if isinstance(e, UserException):
                raise e
            raise UserException(f"JSON-2 failed to get fields for {model}: {str(e)}")

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
        try:
            # Build request payload
            payload = {
                "domain": domain or [],
                "fields": fields or [],
                "offset": offset,
            }

            if limit:
                payload["limit"] = limit
            if order:
                payload["order"] = order

            # Make API call
            records = self.http_client.post(endpoint_path=f"{model}/search_read", json=payload, timeout=30)

            # Validate response
            if not isinstance(records, list):
                raise UserException(f"Unexpected response type from Odoo: {type(records)}")

            logging.info(f"Retrieved {len(records)} records from {model} via JSON-2")
            return records

        except Exception as e:
            # Check if it's an HTTP error
            if hasattr(e, "response") and hasattr(e.response, "status_code"):
                if e.response.status_code == 401:
                    raise UserException("JSON-2 authentication failed: Invalid API key")
                elif e.response.status_code == 403:
                    raise UserException(f"JSON-2 access forbidden: User lacks permission to access {model}")
                elif e.response.status_code == 404:
                    raise UserException(f"JSON-2 model not found: {model} does not exist or API unavailable")
                else:
                    raise UserException(f"JSON-2 failed to fetch data from {model}: HTTP {e.response.status_code}")
            if isinstance(e, UserException):
                raise e
            raise UserException(f"JSON-2 failed to fetch data from {model}: {str(e)}")
