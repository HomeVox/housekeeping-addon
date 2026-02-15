#!/usr/bin/env bashio
set -e

bashio::log.info "Starting Housekeeping v2.0.23..."

# Don't rely on Supervisor API access here.
# We load /data/options.json from inside Python (see src/api/dependencies.py).

exec python3 -m uvicorn src.api.main:app --host 0.0.0.0 --port 8001
