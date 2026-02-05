# Rilono

An AI-powered F1 student visa documentation assistant built with FastAPI and Python. Students can securely organize documents, receive AI guidance, and prepare for visa interviews with confidence.

## Features

- 🔐 **User Authentication**: Secure registration, email verification, and JWT-based sessions
- 📄 **Document Uploads**: Upload and manage visa-related documents with metadata
- 🔒 **Zero-Knowledge Encryption**: Files encrypted with a key derived from the user's password
- 🧠 **AI Validation & Extraction**: Automated document validation and text extraction
- 🧭 **Visa Journey Dashboard**: Track progress and documentation preferences
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

3. **Set Documentation Preferences**:
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

To run in development mode with auto-reload:
```bash
uvicorn app.main:app --reload
```

The `--reload` flag enables automatic reloading when code changes are detected.

## License

This project is open source and available for educational purposes.

## Contributing

Feel free to submit issues, fork the repository, and create pull requests for any improvements.
