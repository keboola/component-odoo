"""
Integration test fixtures.

Manages the lifecycle of a local Odoo instance via docker compose and
provides per-test KBC data directory helpers.

The session-scoped `odoo` fixture starts Odoo + Postgres, creates a test
database with demo data, generates an API key, and tears everything down
after the session.

Set ODOO_EXTERNAL=1 to skip docker compose management and point at an
already-running Odoo instance (use env vars ODOO_URL, ODOO_DB, ODOO_API_KEY,
ODOO_LOGIN to configure it).
"""

import csv
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).parent.parent.parent
COMPOSE_FILE = REPO_ROOT / "docker-compose.test.yml"
SETUP_SCRIPT = REPO_ROOT / "scripts" / "setup_odoo_test.py"


@dataclass
class OdooConfig:
    odoo_url: str
    database: str
    username: str
    api_key: str
    user_id: int


def _wait_for_odoo(url: str, timeout: int = 120) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.post(
                f"{url}/web/database/list",
                json={},
                headers={"Content-Type": "application/json"},
                timeout=5,
            )
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(3)
    raise TimeoutError(f"Odoo at {url} did not become ready within {timeout}s")


@pytest.fixture(scope="session")
def odoo() -> OdooConfig:
    """Start Odoo, set up test DB, yield config, tear down."""
    external = os.environ.get("ODOO_EXTERNAL", "")
    if external:
        # Use an already-running external Odoo — no docker management
        yield OdooConfig(
            odoo_url=os.environ["ODOO_URL"],
            database=os.environ["ODOO_DB"],
            username=os.environ.get("ODOO_LOGIN", "admin@test.com"),
            api_key=os.environ["ODOO_API_KEY"],
            user_id=int(os.environ.get("ODOO_USER_ID", "2")),
        )
        return

    # Start docker compose
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"],
        check=True,
        cwd=REPO_ROOT,
    )

    try:
        # Run setup script — creates DB, API key, prints JSON config
        result = subprocess.run(
            [sys.executable, str(SETUP_SCRIPT)],
            check=True,
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        config_data = json.loads(result.stdout.strip())
        config = OdooConfig(**config_data)

        yield config

    finally:
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"],
            check=False,
            cwd=REPO_ROOT,
        )


@pytest.fixture
def kbc_datadir(tmp_path, monkeypatch) -> Path:
    """Fresh KBC data directory for each test."""
    (tmp_path / "out" / "tables").mkdir(parents=True)
    (tmp_path / "out" / "files").mkdir(parents=True)
    (tmp_path / "in" / "tables").mkdir(parents=True)
    (tmp_path / "in" / "files").mkdir(parents=True)
    monkeypatch.setenv("KBC_DATADIR", str(tmp_path))
    return tmp_path


def write_config(data_dir: Path, parameters: dict, storage: dict | None = None) -> None:
    """Write config.json into data dir."""
    config: dict = {"parameters": parameters}
    if storage:
        config["storage"] = storage
    (data_dir / "config.json").write_text(json.dumps(config))


def write_input_csv(data_dir: Path, filename: str, rows: list[dict]) -> None:
    """Write a CSV into in/tables/."""
    path = data_dir / "in" / "tables" / filename
    if rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        path.write_text("")


def read_csv(data_dir: Path, table_name: str) -> list[dict]:
    """Read an output CSV table."""
    csv_path = data_dir / "out" / "tables" / f"{table_name}.csv"
    with open(csv_path) as f:
        return list(csv.DictReader(f))


def read_state(data_dir: Path) -> dict:
    """Read out/state.json."""
    with open(data_dir / "out" / "state.json") as f:
        return json.load(f)
