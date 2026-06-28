#!/usr/bin/env bash
# Run the app on http://localhost:8000 using the LIVE database + production
# credentials from .env (your explicit choice). Only the three vars below are
# overridden so localhost http + Google OAuth work; DATABASE_URL, Razorpay,
# Gemini and GOOGLE_OAUTH_* all come from .env.
#
# NOTE: on first boot the startup migrations apply to the live DB. Back it up first.
# Google login also needs http://localhost:8000/api/auth/oauth/google/callback
# registered as an authorized redirect URI in your Google OAuth client.
set -a
ENVIRONMENT=development          # allow the non-secure session cookie over http
BASE_URL=http://localhost:8000   # OAuth redirect comes back here
AUTH_COOKIE_DOMAIN=              # host-only cookie so localhost keeps the session
set +a

exec uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
