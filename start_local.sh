#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# One-command local dev setup.
# Use lvh.me to avoid Chrome's cached HTTPS/HSTS state for localtest.me.
export ENVIRONMENT=development
export ENTERPRISE_ROOT_DOMAIN=lvh.me
export ENTERPRISE_PORTAL_SCHEME=http
export ENTERPRISE_PORTAL_PORT=8000
export AUTH_COOKIE_DOMAIN=.lvh.me
export AUTH_COOKIE_SECURE=false
export AUTH_COOKIE_SAMESITE=lax

echo "Starting Rilono local app..."
echo "Open this URL:"
echo "  http://acme.lvh.me:8000/enterprise"
echo
echo "Do not use https for this local setup."
echo

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
