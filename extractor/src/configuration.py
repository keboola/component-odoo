"""
Configuration schema for Odoo Extractor.

Extends shared connection configuration with extraction-specific fields.
"""

import json
from typing import Any

from keboola.component.exceptions import UserException
from pydantic import Field

from shared.connection import OdooConnectionConfig


class Configuration(OdooConnectionConfig):
    """Odoo Extractor configuration — connection + extraction settings."""

    model: str = Field(default="", description="Odoo model name")
    fields: list[str] | None = Field(default=None, description="Fields to extract")
    domain: str | None = Field(default=None, description="Odoo domain filter as JSON string")
    incremental: bool = Field(default=False, description="Enable incremental loading")
    page_size: int = Field(default=1000, description="Number of records per page")

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
