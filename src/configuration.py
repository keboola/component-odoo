"""
Configuration schema for Odoo Extractor.

Uses Pydantic for validation with modern Python 3.9+ type hints.
"""

import json
from typing import Any

from keboola.component.exceptions import UserException
from pydantic import BaseModel, Field, ValidationError, field_validator

PROTOCOL_XMLRPC = "xmlrpc"


class Configuration(BaseModel):
    """Configuration for Odoo Extractor - supports both connection and extraction settings."""

    odoo_url: str = Field(description="Odoo instance URL")
    database: str = Field(default="", description="Database name")
    username: str | None = Field(default=None, description="Username/email")
    api_key: str = Field(default="", alias="#api_key", description="API key")
    api_protocol: str = Field(default=PROTOCOL_XMLRPC, description="API protocol: xmlrpc or json2")

    model: str = Field(default="", description="Odoo model name")
    fields: list[str] | None = Field(default=None, description="Fields to extract")
    domain: str | None = Field(default=None, description="Odoo domain filter as JSON string")
    incremental: bool = Field(default=False, description="Enable incremental loading")
    page_size: int = Field(default=1000, description="Number of records per page")

    def __init__(self, **data: Any) -> None:
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

    @field_validator("odoo_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("Odoo URL must start with http:// or https://")
        return v.rstrip("/")

    @property
    def table_name(self) -> str:
        if self.model:
            return f"{self.model.replace('.', '_')}.csv"
        return ""

    def get_domain(self) -> list[Any]:
        if not self.domain:
            return []
        try:
            return json.loads(self.domain)
        except json.JSONDecodeError:
            raise UserException(f"Invalid domain JSON: {self.domain}")

    class Config:
        populate_by_name = True
