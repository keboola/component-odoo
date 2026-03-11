"""
Shared pytest fixtures for the Odoo component test suite.
"""

import csv
import json
from pathlib import Path

import pytest


@pytest.fixture
def data_dir(tmp_path):
    """Keboola data directory with standard layout, auto-cleaned after each test."""
    (tmp_path / "out" / "tables").mkdir(parents=True)
    (tmp_path / "in").mkdir()
    return tmp_path


@pytest.fixture
def kbc_datadir(data_dir, monkeypatch):
    """Set KBC_DATADIR env var to the temp data directory."""
    monkeypatch.setenv("KBC_DATADIR", str(data_dir))
    return data_dir


def write_config(data_dir: Path, parameters: dict) -> None:
    """Write a Keboola config.json into the data directory."""
    (data_dir / "config.json").write_text(json.dumps({"parameters": parameters}))


def write_state(data_dir: Path, state: dict) -> None:
    """Write in/state.json into the data directory."""
    (data_dir / "in" / "state.json").write_text(json.dumps(state))


def read_csv(data_dir: Path, table_name: str) -> list[dict]:
    """Read an output CSV table and return records as a list of dicts."""
    csv_path = data_dir / "out" / "tables" / f"{table_name}.csv"
    with open(csv_path) as f:
        return list(csv.DictReader(f))


def read_state(data_dir: Path) -> dict:
    """Read the output state.json file."""
    with open(data_dir / "out" / "state.json") as f:
        return json.load(f)
