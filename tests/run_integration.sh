#!/bin/sh
# Thin wrapper: the cross-platform launcher lives in run_integration.py.
# Usage: tests/run_integration.sh [pytest args...]
exec python3 "$(dirname "$0")/run_integration.py" "$@"
