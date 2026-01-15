"""
Odoo JSON-2 API Client

Handles authentication and data extraction from Odoo ERP via JSON-2 API.
Compatible with Odoo v19+.
"""

import logging
from typing import Any

import requests

from keboola.component.exceptions import UserException


class Json2Client:
    """Client for interacting with Odoo JSON-2 API (Odoo 19+)."""

    def __init__(self, url: str, database: str, username: str, api_key: str) -> None:
        """
        Initialize Odoo JSON-2 client.

        Args:
            url: Odoo instance URL (e.g., https://mycompany.odoo.com)
            database: Database name
            username: User email/login (for reference, not used in auth)
            api_key: API key (bearer token)
        """
        self.url: str = url.rstrip("/")
        self.database: str = database
        self.username: str = username  # Not used in auth, kept for compatibility
        self.api_key: str = api_key

        # Base URL for JSON-2 API
        self.base_url: str = f"{self.url}/json/2"

        # Default headers for all requests
        self.headers: dict[str, str] = {
            "Authorization": f"bearer {self.api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "keboola-odoo-extractor/1.0",
        }

        # Add database header if specified
        if self.database:
            self.headers["X-Odoo-Database"] = self.database

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
            response = requests.get(f"{self.url}/web/version", timeout=10)
            response.raise_for_status()

            version_info = response.json()
            version = version_info.get("version", "unknown")

            logging.info(f"Detected Odoo version: {version} via JSON-2")
            return version

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise UserException(
                    "JSON-2 version check failed: HTTP 404 - /web/version endpoint not found"
                )
            else:
                raise UserException(
                    f"JSON-2 version check failed: HTTP {e.response.status_code}"
                )
        except Exception as e:
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
            response = requests.post(
                f"{self.base_url}/res.users/search_read",
                headers=self.headers,
                json={"domain": [], "limit": 1, "fields": ["id"]},
                timeout=10,
            )
            response.raise_for_status()

            # If we got here, authentication worked
            logging.info("JSON-2 authentication successful")
            return {"version": version, "protocol": "JSON-2"}

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise UserException("JSON-2 authentication failed: Invalid API key")
            elif e.response.status_code == 403:
                raise UserException("JSON-2 authentication failed: Access forbidden")
            elif e.response.status_code == 404:
                raise UserException(
                    "JSON-2 API not available (HTTP 404) - Odoo instance may be older than v19"
                )
            else:
                raise UserException(
                    f"JSON-2 connection failed: HTTP {e.response.status_code}"
                )
        except UserException as e:
            raise e
        except Exception as e:
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
            response = requests.post(
                f"{self.base_url}/ir.model/search_read",
                headers=self.headers,
                json={"domain": [], "fields": ["model", "name"]},
                timeout=30,
            )
            response.raise_for_status()

            models = response.json()
            logging.info(f"Retrieved {len(models)} models via JSON-2")
            return models

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise UserException("JSON-2 authentication failed: Invalid API key")
            elif e.response.status_code == 403:
                raise UserException(
                    "JSON-2 access forbidden: User lacks permission to list models"
                )
            elif e.response.status_code == 404:
                raise UserException("JSON-2 API not available (HTTP 404)")
            else:
                raise UserException(
                    f"JSON-2 failed to list models: HTTP {e.response.status_code}"
                )
        except UserException as e:
            raise e
        except Exception as e:
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
            response = requests.post(
                f"{self.base_url}/{model}/fields_get",
                headers=self.headers,
                json={"attributes": ["string", "type", "help", "required"]},
                timeout=30,
            )
            response.raise_for_status()

            fields = response.json()

            if not isinstance(fields, dict):
                raise UserException(
                    f"Unexpected response type from Odoo: {type(fields)}"
                )

            logging.info(f"Retrieved {len(fields)} fields for {model} via JSON-2")
            return fields

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise UserException("JSON-2 authentication failed: Invalid API key")
            elif e.response.status_code == 403:
                raise UserException(
                    f"JSON-2 access forbidden: User lacks permission to access {model}"
                )
            elif e.response.status_code == 404:
                raise UserException(
                    f"JSON-2 model not found: {model} does not exist or API unavailable"
                )
            else:
                raise UserException(
                    f"JSON-2 failed to get fields for {model}: HTTP {e.response.status_code}"
                )
        except UserException as e:
            raise e
        except Exception as e:
            raise UserException(f"JSON-2 failed to get fields for {model}: {str(e)}")
