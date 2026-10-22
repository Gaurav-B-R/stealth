# Rilono

An AI-powered study-abroad platform built with FastAPI and Python. Students can securely organize documents, receive AI guidance, and prepare for visa interviews with confidence.

## Features

- 🔐 **User Authentication**: Secure registration, email verification, and JWT-based sessions
- 📄 **Document Uploads**: Upload and manage visa-related documents with metadata
- 🔒 **Zero-Knowledge Encryption**: Files encrypted with a key derived from the user's password
- 🧠 **AI Validation & Extraction**: Automated document validation and text extraction
- 🧭 **Visa Journey Dashboard**: Track progress and destination preferences
- 💬 **AI Chat Assistant**: Context-aware guidance based on uploaded documents
- 🎨 **Modern UI**: Beautiful, responsive design with smooth animations

## Tech Stack

- **Backend**: FastAPI (Python)
- **Database**: SQLite (can be easily switched to PostgreSQL)
- **Authentication**: JWT (JSON Web Tokens)
- **Frontend**: HTML, CSS, JavaScript (Vanilla)
- **ORM**: SQLAlchemy

## Installation

### Prerequisites

- Python 3.8 or higher
- pip (Python package manager)

### Setup Steps

1. **Clone or navigate to the project directory**:
   ```bash
   cd stealth
   ```

2. **Create a virtual environment** (recommended):
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Mac/Linux
   # or
   venv\Scripts\activate  # On Windows
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**:
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` and update the `SECRET_KEY` with a secure random string (you can generate one using Python):
   ```python
   import secrets
   print(secrets.token_urlsafe(32))
   ```

5. **Run the application**:
   ```bash
   uvicorn app.main:app --reload
   ```

6. **Access the application**:
   - Web interface: http://localhost:8000
   - API documentation: http://localhost:8000/docs
   - Alternative API docs: http://localhost:8000/redoc

## Usage

### For Students

1. **Register an Account**:
   - Click "Register" in the navigation bar
   - Fill in your details (email, password, etc.)
   - Verify your email to activate your account

2. **Login**:
   - Click "Login" in the navigation bar
   - Enter your email and password

3. **Set Destination Preferences**:
   - Open your dashboard
   - Choose target country, intake, and year

4. **Upload Documents**:
   - Upload visa-related documents
   - Provide your password to encrypt the file
   - Review validation feedback

5. **Use AI Guidance**:
   - Ask questions in the AI chat
   - Get guidance based on your uploaded documents

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register a new user
- `POST /api/auth/login` - Login and get access token
- `GET /api/auth/me` - Get current user info

### Documents
- `POST /api/documents/upload` - Upload a document (requires authentication)
- `GET /api/documents/my-documents` - List your documents (requires authentication)
- `GET /api/documents/{document_id}` - Get a document (requires authentication)
- `GET /api/documents/{document_id}/extracted-text` - Get extracted text (requires authentication)

### AI Chat
- `POST /api/ai-chat/chat` - Send a chat message (requires authentication)

## Database

The application uses SQLite by default, which creates a `rilono.db` file in the project root. The database is automatically created when you first run the application. (Note: The database filename can be customized in the database configuration.)

To use PostgreSQL instead:
1. Update `DATABASE_URL` in `.env` to your PostgreSQL connection string
2. Install PostgreSQL adapter: `pip install psycopg2-binary`

## Project Structure

```
stealth/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application entry point
│   ├── database.py          # Database configuration
│   ├── models.py            # SQLAlchemy models
│   ├── schemas.py           # Pydantic schemas
│   ├── auth.py              # Authentication utilities
│   └── routers/
│       ├── __init__.py
│       ├── auth.py          # Authentication routes
│       ├── documents.py     # Document upload and management routes
│       ├── ai_chat.py       # AI chat routes
│       ├── profile.py       # Profile and account routes
│       └── upload.py        # Upload helpers
├── static/
│   ├── index.html           # Main HTML page
│   ├── styles.css           # CSS styles
│   └── app.js               # Frontend JavaScript
├── requirements.txt         # Python dependencies
├── .env.example            # Environment variables template
└── README.md               # This file
```

## Security Notes

- Always change the `SECRET_KEY` in production
- Use environment variables for sensitive configuration
- Consider using HTTPS in production
- Regularly update dependencies for security patches

## Development

AI cost accounting, an isolated local review of retained records, calculated per-profile costs, actual Google billing, and validation: [AI cost accounting guide](docs/ai-cost-accounting.md).

To run in development mode with auto-reload:
```bash
uvicorn app.main:app --reload
```

The `--reload` flag enables automatic reloading when code changes are detected.

## Marketing Contacts Sync (Resend)

Use this to sync eligible users from your Postgres `users` table to a Resend Audience.

Eligibility filter:
- `is_active = true`
- `email_verified = true`
- `email_notifications_enabled = true`
- `email is not null`

### Required env vars

```bash
RESEND_API_KEY=...
RESEND_TRANSACTIONAL_FROM_EMAIL=noreply@rilono.com
RESEND_MARKETING_SEGMENT_ID=...
```

Backward compatibility: `RESEND_MARKETING_AUDIENCE_ID` is also accepted.

Optional:

```bash
GEMINI_MODEL=gemini-3.1-pro-preview         # leads the app-wide default chain (this is also the default)
RILONO_AI_CHAT_MODEL=gemini-3.5-flash       # example: pin a cheaper model for one surface
GEMINI_DOCUMENT_MODEL=gemini-3.5-flash
DAILY_AI_NOTIFIER_MODEL=gemini-3.5-flash
DAILY_AI_NOTIFIER_DORMANT_AFTER_DAYS=30    # no login for this many days → account is dormant
DAILY_AI_NOTIFIER_DORMANT_CADENCE_DAYS=14  # dormant accounts are scanned/emailed once per this many days (0 AFTER_DAYS = off)
RESEND_CONTACTS_SYNC_BATCH_SIZE=100
RESEND_CONTACTS_SYNC_TIMEOUT_SECONDS=30
RESEND_CONTACTS_SYNC_UNSUBSCRIBE_INELIGIBLE=false
RESEND_CONTACTS_SYNC_REQUEST_INTERVAL_SECONDS=0.55
RESEND_CONTACTS_SYNC_MAX_RETRIES=4
RESEND_CONTACTS_SYNC_RETRY_MAX_SECONDS=6
```

Keep AI model names in env instead of hard-coding preview model IDs. If a provider retires a model, update the relevant `*_MODEL` or comma-separated `*_MODEL_CANDIDATES` env value.

**Retired models:** Gemini 2.5 (`gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-2.5-flash-lite`) was retired on Vertex on 2026-10-20, and 2.0 before it. This README used to show `gemini-2.5-flash` in the examples above. If an environment copied those values, replace them: a retired id fails on every call before the chain falls back to a pricier model. The code's defaults no longer contain any 2.5 or 2.0 id. The enterprise assistant, Deep Scan, upload reading and the Chrome-extension copilot default to the cheap chain `gemini-3.1-flash-lite` → `gemini-3.5-flash` → `gemini-3.1-pro-preview`. `RILONO_AI_CHAT_MODEL` no longer steers the enterprise Chrome-extension copilot; that is `ENTERPRISE_COPILOT_MODEL`.

### Run manually

```bash
python -m app.services.resend_contacts_sync --dry-run
python -m app.services.resend_contacts_sync
```

### Render Cron command

Set a Cron Job command to:

```bash
python -m app.services.resend_contacts_sync
```

If you want to remove ineligible contacts from the marketing segment:

```bash
python -m app.services.resend_contacts_sync --unsubscribe-ineligible
```

This does not mark contacts as unsubscribed in Resend. Notification opt-outs stay app-level so transactional emails like password resets, email verification, and enterprise invites remain deliverable.

## Enterprise (B2B) Pricing Configuration

The enterprise plans, limits, AI credit prices, monthly AI reading allowance, tax and currency rules are set by `ENTERPRISE_*` environment variables. All of them have defaults (pricing v2, 2026-10-22), and customer-facing copy is generated from them. The ones you are most likely to touch:

```bash
ENTERPRISE_GST_PERCENT=18             # GST on INR plan prices; 0 = no tax and no "+ GST" anywhere
ENTERPRISE_YEARLY_ENABLED=false       # sell yearly plans (10x monthly, "2 months free"); off until the reading quality check passes
ENTERPRISE_AI_PAUSE_ON_EXPIRY=true    # pause every AI feature when the trial ends or a paid plan lapses
ENTERPRISE_FILE_LIMIT_GRACE_DAYS=14   # days an org may stay over its open-file limit; 0 = hard cap
ENTERPRISE_INR_REGION_COUNTRIES=IN,NP,BD,LK,NG,GH,KE   # charged INR only; everywhere else never INR
ENTERPRISE_COUPON_MAX_PERCENT=15      # largest discount a code may give
# ENTERPRISE_READ_MODEL_CANDIDATES=gemini-3.1-flash-lite,gemini-3.5-flash   # upload-reading chain (unset = cheap chain)
```

Setting an old price or limit variable (for example `ENTERPRISE_STARTER_MONTHLY_PAISE` or `ENTERPRISE_COPILOT_INVITE_MESSAGES`) overrides the new defaults. The full list with defaults, meanings and the production checklist is in [docs/runbook.md](docs/runbook.md#7-enterprise-pricing-v2-configuration). The decision record is [docs/decisions.md](docs/decisions.md) (D-009).

## License

This project is open source and available for educational purposes.

## Contributing

Feel free to submit issues, fork the repository, and create pull requests for any improvements.

For project memory and operational docs, start at `docs/README.md`.
Before shipping changes, run `docs/workflows/docs-update-checklist.md`.
