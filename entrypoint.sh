#!/bin/sh
# FileMorph container entrypoint
# Handles first-run API key generation, then starts the server.
set -e

KEYS_FILE=/app/data/api_keys.json

# Ensure data directory exists
mkdir -p /app/data

# Check if any API keys are stored yet
need_key=1
if [ -f "$KEYS_FILE" ]; then
    key_count=$(python -c "
import json, sys
try:
    data = json.load(open('$KEYS_FILE'))
    print(len(data.get('keys', [])))
except Exception:
    print(0)
")
    if [ "$key_count" -gt "0" ]; then
        need_key=0
    fi
fi

if [ "$need_key" = "1" ]; then
    API_KEY=$(python scripts/first_run.py)

    echo ""
    echo "================================================================"
    echo "  FileMorph - First Run Setup"
    echo "================================================================"
    echo "  API KEY: $API_KEY"
    echo "================================================================"
    echo "  IMPORTANT: Save this key - it will NOT be shown again."
    echo "  Enter it in the Web UI under the 'API Key' field."
    echo "================================================================"
    echo ""
fi

# --timeout-keep-alive 65 aligns with a typical CDN idle timeout (~100 s) so
# the proxy can reuse upstream TCP connections across multiple user requests
# instead of forcing a fresh handshake on each keepalive-expired socket.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 65
