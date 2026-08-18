#!/bin/sh

set -e

python3 src/modules/generate_hidden_imports.py

exec uvicorn src.main:app --host 0.0.0.0 --port 8000
