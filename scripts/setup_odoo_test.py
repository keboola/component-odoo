#!/usr/bin/env python3
"""
Unattended Odoo test database setup.

Creates a fresh test database with demo data and generates an API key
for use in integration tests. Outputs JSON config to stdout.

Usage:
    python scripts/setup_odoo_test.py
    python scripts/setup_odoo_test.py > /tmp/odoo_test_config.json
"""

import binascii
import json
import os
import sys
import time
import xmlrpc.client

import psycopg2
import requests
from passlib.context import CryptContext

ODOO_URL = os.environ.get("ODOO_URL", "http://localhost:8069")
DB_NAME = os.environ.get("ODOO_DB", "test-db")
ADMIN_LOGIN = os.environ.get("ODOO_LOGIN", "admin@test.com")
ADMIN_PASSWORD = os.environ.get("ODOO_PASSWORD", "admin123")
PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = int(os.environ.get("PG_PORT", "5432"))
PG_USER = os.environ.get("PG_USER", "odoo")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "odoo")

# Must match Odoo's constants exactly
API_KEY_SIZE = 20
INDEX_SIZE = 8
KEY_CRYPT_CONTEXT = CryptContext(["pbkdf2_sha512"], pbkdf2_sha512__rounds=6000)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def wait_for_odoo(timeout: int = 120) -> None:
    log(f"Waiting for Odoo at {ODOO_URL}...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.post(
                f"{ODOO_URL}/web/database/list",
                json={},
                headers={"Content-Type": "application/json"},
                timeout=5,
            )
            if r.status_code == 200:
                log("Odoo is ready.")
                return
        except Exception:
            pass
        time.sleep(3)
    raise TimeoutError(f"Odoo did not become ready within {timeout}s")


def create_database() -> None:
    log(f"Creating database '{DB_NAME}' with demo data...")
    r = requests.post(
        f"{ODOO_URL}/web/database/create",
        data={
            "master_pwd": "admin",
            "name": DB_NAME,
            "login": ADMIN_LOGIN,
            "password": ADMIN_PASSWORD,
            "demo": "true",
            "lang": "en_US",
            "phone": "",
        },
        timeout=30,
        allow_redirects=False,
    )
    if r.status_code not in (200, 303):
        raise RuntimeError(f"Database create failed: HTTP {r.status_code}: {r.text[:200]}")
    log(f"Database '{DB_NAME}' created.")


def wait_for_database(timeout: int = 180) -> None:
    log(f"Waiting for database '{DB_NAME}' to be ready (demo data install)...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.post(
                f"{ODOO_URL}/web/database/list",
                json={},
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            if r.status_code == 200:
                dbs = r.json().get("result", [])
                if DB_NAME in dbs:
                    # Also verify RPC is functional
                    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
                    uid = common.authenticate(DB_NAME, ADMIN_LOGIN, ADMIN_PASSWORD, {})
                    if uid:
                        log(f"Database ready. Admin UID: {uid}")
                        return
        except Exception:
            pass
        time.sleep(5)
    raise TimeoutError(f"Database '{DB_NAME}' did not become ready within {timeout}s")


def get_admin_uid() -> int:
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(DB_NAME, ADMIN_LOGIN, ADMIN_PASSWORD, {})
    if not uid:
        raise RuntimeError("Failed to authenticate as admin")
    return uid


def create_api_key(user_id: int) -> str:
    """Insert an API key directly into Postgres — same logic as Odoo's _generate()."""
    log("Creating API key via direct Postgres insert...")
    plaintext_key = binascii.hexlify(os.urandom(API_KEY_SIZE)).decode()
    key_hash = KEY_CRYPT_CONTEXT.hash(plaintext_key)
    key_index = plaintext_key[:INDEX_SIZE]

    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=DB_NAME,
        user=PG_USER,
        password=PG_PASSWORD,
    )
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO res_users_apikeys (name, user_id, scope, expiration_date, key, index)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    ("integration-test-key", user_id, None, None, key_hash, key_index),
                )
                key_id = cur.fetchone()[0]
    finally:
        conn.close()

    log(f"API key created (id={key_id}).")
    return plaintext_key


def main() -> None:
    wait_for_odoo()

    # Check if DB already exists (re-run safe)
    r = requests.post(
        f"{ODOO_URL}/web/database/list",
        json={},
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    existing_dbs = r.json().get("result", [])
    if DB_NAME not in existing_dbs:
        create_database()
        wait_for_database()
    else:
        log(f"Database '{DB_NAME}' already exists, skipping creation.")

    uid = get_admin_uid()
    api_key = create_api_key(uid)

    config = {
        "odoo_url": ODOO_URL,
        "database": DB_NAME,
        "username": ADMIN_LOGIN,
        "api_key": api_key,
        "user_id": uid,
    }
    print(json.dumps(config))
    log("Setup complete.")


if __name__ == "__main__":
    main()
