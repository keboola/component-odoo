"""
Configuration schema for Odoo Extractor.

Uses Pydantic for validation with modern Python 3.9+ type hints.
"""

import logging
from typing import Any

from keboola.component.exceptions import UserException
from pydantic import BaseModel, Field, ValidationError, field_validator

# Protocol constants
PROTOCOL_XMLRPC = "xmlrpc"


class OdooEndpoint(BaseModel):
    """Configuration for an Odoo model extraction."""

    model: str = Field(default="", description="Odoo model name (e.g., 'res.partner', 'sale.order')")
    output_table: str | None = Field(default=None, description="Output table name (auto-generated if not provided)")
    fields: list[str] | None = Field(default=None, description="Fields to extract (all if empty)")
    domain: list[Any] | None = Field(default=None, description="Odoo domain filter")
    limit: int | None = Field(default=None, description="Maximum records to extract")
    order: str | None = Field(default="id asc", description="Sort order")
    incremental: bool = Field(default=False, description="Enable incremental loading")
    primary_key: list[str] | None = Field(default=None, description="Primary key columns")

    @property
    def table_name(self) -> str:
        """Get output table name, auto-generating from model if not provided."""
        if self.output_table:
            return self.output_table
        # Convert model name: res.partner -> res_partner.csv
        return f"{self.model.replace('.', '_')}.csv"


class Configuration(BaseModel):
    """Main configuration for Odoo Extractor."""

    # Connection settings
    odoo_url: str = Field(description="Odoo instance URL")
    database: str = Field(default="", description="Database name")
    username: str | None = Field(default=None, description="Username/email")
    api_key: str = Field(default="", alias="#api_key", description="API key")
    api_protocol: str = Field(default=PROTOCOL_XMLRPC, description="API protocol: xmlrpc or json2")

    # Extraction configuration
    endpoints: list[OdooEndpoint] = Field(default=[], description="List of models to extract")

    # Optional settings
    debug: bool = Field(default=False, description="Enable debug logging")

    def __init__(self, **data: Any) -> None:
        """Initialize configuration with validation."""
        try:
            super().__init__(**data)
        except ValidationError as e:
            error_messages = []
            for err in e.errors():
                if err["loc"]:
                    error_messages.append(f"{err['loc'][0]}: {err['msg']}")
                else:
                    error_messages.append(err["msg"])
            raise UserException(f"Configuration validation error: {', '.join(error_messages)}")

        if self.debug:
            logging.getLogger().setLevel(logging.DEBUG)
            logging.debug("Component running in DEBUG mode")

    @field_validator("odoo_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate Odoo URL format."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("Odoo URL must start with http:// or https://")
        return v.rstrip("/")

    class Config:
        """Pydantic configuration."""

        populate_by_name = True  # Allow both 'api_key' and '#api_key'
