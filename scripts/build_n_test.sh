#!/bin/sh
set -e

flake8
uv run pytest
