"""
Configuration schema for Odoo Writer.

Extends shared connection configuration with write-specific fields.
"""

from pydantic import Field
from shared.connection import OdooConnectionConfig


class Configuration(OdooConnectionConfig):
    """Odoo Writer configuration — connection + write settings."""

    model: str = Field(description="Odoo model name to write into (e.g. 'res.partner')")
    input_table: str = Field(description="Input CSV table filename (e.g. 'partners.csv')")
    batch_size: int = Field(default=100, description="Number of records per create() API call")
