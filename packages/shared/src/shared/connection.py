"""
Shared Odoo connection configuration.

Contains connection fields used by both extractor and writer components.
"""

from typing import Any

from keboola.component.exceptions import UserException
from pydantic import BaseModel, Field, ValidationError, field_validator

PROTOCOL_XMLRPC = "xmlrpc"
PROTOCOL_JSON2 = "json2"


class OdooConnectionConfig(BaseModel):
    """Shared Odoo connection configuration — URL, credentials, protocol."""

    odoo_url: str = Field(description="Odoo instance URL")
    database: str = Field(default="", description="Database name")
    username: str | None = Field(default=None, description="Username/email")
    api_key: str = Field(default="", alias="#api_key", description="API key")
    api_protocol: str = Field(default=PROTOCOL_XMLRPC, description="API protocol: xmlrpc or json2")

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

    class Config:
        populate_by_name = True
