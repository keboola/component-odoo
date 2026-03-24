"""
Configuration schema for Odoo Writer.

Extends shared connection configuration with write-specific fields.
"""

from pydantic import BaseModel, Field
from shared.connection import OdooConnectionConfig


class FieldMapping(BaseModel):
    """Maps a source CSV column to an Odoo model field."""

    source_column: str = ""
    destination_field: str = ""


class Configuration(OdooConnectionConfig):
    """Odoo Writer configuration — connection + write settings."""

    model: str = Field(default="", description="Odoo model name to write into (e.g. 'res.partner')")
    input_table: str = Field(default="", description="Input CSV table filename (e.g. 'partners.csv')")
    batch_size: int = Field(default=100, description="Number of records per create() API call")
    field_mapping: list[FieldMapping] = Field(default_factory=list)
    continue_on_error: bool = False
