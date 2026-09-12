#!/usr/bin/env bash
# Run the app on http://localhost:8000 using the LIVE database + production
# credentials from .env (your explicit choice). Only the three vars below are
# overridden so localhost http + Google OAuth work; DATABASE_URL, Razorpay,
# Gemini and GOOGLE_OAUTH_* all come from .env.
#
# NOTE: on first boot the startup migrations apply to the live DB. Back it up first.
# Google login also needs http://localhost:8000/api/auth/oauth/google/callback
# registered as an authorized redirect URI in your Google OAuth client.
cd "$(dirname "$0")"

set -a
ENVIRONMENT=development          # allow the non-secure session cookie over http
BASE_URL=http://localhost:8000   # OAuth redirect comes back here
AUTH_COOKIE_DOMAIN=              # host-only cookie so localhost keeps the session
set +a

# Google billing read configuration for the admin AI Costs page. The main app never reads
# data/ai_billing.local.env itself (only scripts/preview_ai_costs.py does), so export it here,
# parsed with the same dotenv grammar that script uses (shell-sourcing would drop unquoted
# values containing spaces, such as service names, and silently fall back to defaults).
if [ -f data/ai_billing.local.env ]; then
    billing_exports="$(./venv/bin/python - <<'PY'
import shlex
from dotenv import dotenv_values
for key, value in dotenv_values("data/ai_billing.local.env").items():
    if key.startswith("AI_BILLING_") and key != "AI_BILLING_SYNC_ENABLED" and value is not None:
        print(f"export {key}={shlex.quote(value)}")
PY
)" || { echo "run_local.sh: could not read data/ai_billing.local.env" >&2; exit 1; }
    eval "$billing_exports"
fi
# Never let this app run the daily billing worker: it uses the LIVE database and would compete for
# the prod lease. An explicit value here beats both a shell export and any value in .env.
# Note that Sync billing on this app writes the snapshot into the production tables (same data the
# prod worker writes); use scripts/preview_ai_costs.py for local experiments.
export AI_BILLING_SYNC_ENABLED=false

exec uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
