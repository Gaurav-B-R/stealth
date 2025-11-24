# Rilono

A beautiful and modern marketplace platform built with FastAPI and Python, designed specifically for student communities. Students can create accounts, list items for sale, and browse items from other students.

## Features

- 🔐 **User Authentication**: Secure registration and login with JWT tokens
- 📦 **Item Listings**: Create, update, and delete item listings
- 🖼️ **Multiple Images**: Upload up to 10 images per item listing
- 📍 **Address Autocomplete**: Google Places integration for pickup location
- 🔍 **Search & Filter**: Search items by title/description, filter by category and price range
- 👤 **User Profiles**: View your own listings and manage your items
- 🎨 **Modern UI**: Beautiful, responsive design with smooth animations
- 🏷️ **Categories**: Organize items by category (Textbooks, Electronics, Furniture, Clothing, Sports, Sublease, Other)
- ✅ **Sold Status**: Mark items as sold when they're purchased

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

5. **Set up Google Places API (Optional but recommended)**:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select an existing one
   - Enable the "Places API" and "Maps JavaScript API"
   - Create an API key
   - In `static/index.html`, replace `YOUR_GOOGLE_API_KEY` with your actual API key
   - **Note**: Without the API key, address input will work as a basic text field (autocomplete will be disabled)

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
   - Fill in your details (email, username, password, etc.)
   - Click "Register"

2. **Login**:
   - Click "Login" in the navigation bar
   - Enter your username and password
   - You'll be automatically logged in

3. **List an Item for Sale**:
   - Click "Sell Item" in the navigation bar
   - Fill in the item details (title, description, price, category, etc.)
   - Click "List Item"
   - Your item will appear in Rilono

4. **Browse Items**:
   - Use the search bar to search by keywords
   - Filter by category using the dropdown
   - Set price range using min/max price fields
   - Click "Search" to apply filters

5. **Manage Your Listings**:
   - Click "My Listings" to see all your items
   - Mark items as "Sold" when they're purchased
   - Delete items you no longer want to sell

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register a new user
- `POST /api/auth/login` - Login and get access token
- `GET /api/auth/me` - Get current user info

### Items
- `GET /api/items/` - Get all items (with optional filters)
- `GET /api/items/{item_id}` - Get a specific item
- `POST /api/items/` - Create a new item (requires authentication)
- `PUT /api/items/{item_id}` - Update an item (requires authentication, owner only)
- `DELETE /api/items/{item_id}` - Delete an item (requires authentication, owner only)
- `GET /api/items/my/listings` - Get current user's items (requires authentication)

## Database

The application uses SQLite by default, which creates a `student_marketplace.db` file in the project root. The database is automatically created when you first run the application. (Note: The database filename can be customized in the database configuration.)

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
│       └── items.py         # Item routes
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

