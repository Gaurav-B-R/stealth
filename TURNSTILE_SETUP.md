# Cloudflare Turnstile Setup Guide

This application uses Cloudflare Turnstile for bot protection on login and registration forms.

## Setup Instructions

### 1. Get Turnstile Keys from Cloudflare Dashboard

1. **Log in to Cloudflare Dashboard**
   - Go to [https://dash.cloudflare.com/](https://dash.cloudflare.com/)
   - Sign in with your Cloudflare account

2. **Navigate to Turnstile**
   - In the left sidebar, look for **"Turnstile"** (usually under Security or in the main menu)
   - Click on it to open the Turnstile dashboard

3. **Create a New Widget**
   - Click the **"Add Widget"** or **"Create"** button
   - Fill in the widget details:
     - **Widget name**: Give it a descriptive name (e.g., "Rilono Login/Register")
     - **Hostname Management**: Add your domain(s) where the widget will be used
       - For local development: You can use `localhost` or skip this
       - For production: Add your actual domain (e.g., `yourdomain.com`)
     - **Widget Mode**: Choose one of:
       - **Managed** (Recommended): Cloudflare decides when to show challenges
       - **Non-interactive**: Shows a loading bar challenge
       - **Invisible**: No visible challenge (most user-friendly)
     - **Pre-clearance**: Select "No" (unless you have specific needs)

4. **Get Your Keys**
   - After creating the widget, you'll be taken to the widget details page
   - You'll see two keys displayed:
     - **Site Key**: This is your public key (safe to expose in frontend code)
     - **Secret Key**: This is your private key (keep it secret, never expose it)
   - **Copy both keys** - you'll need them in the next step

   **Alternative**: If you already have a widget created:
   - Go to the Turnstile dashboard
   - Click on your widget name
   - The keys will be displayed on the widget details page
   - You can also click **"View"** or **"Show"** next to the Secret Key to reveal it

### 2. Configure Environment Variables

1. **Create or edit your `.env` file** in the project root directory

2. **Add the Turnstile keys** you copied from Cloudflare:

```bash
# Cloudflare Turnstile Configuration
TURNSTILE_SITE_KEY=0x4AAAAAAABkMYinukE8K5O0  # Replace with your actual Site Key
TURNSTILE_SECRET_KEY=0x4AAAAAAABkMYinukE8K5O0  # Replace with your actual Secret Key

# Optional: Set to "development" to allow bypassing Turnstile when keys are not set
# In development mode, if keys are missing, verification will be skipped
ENVIRONMENT=development
```

3. **Important Notes**:
   - **Site Key**: This is public and will be sent to the frontend (it's safe to expose)
   - **Secret Key**: This is private and should NEVER be committed to version control
   - Make sure your `.env` file is in `.gitignore` (it should be by default)
   - The keys look like: `0x4AAAAAAABkMYinukE8K5O0` (they start with `0x`)

4. **For Production**:
   - Set `ENVIRONMENT=production` (or remove it, as production is the default)
   - Make sure both keys are set, otherwise authentication will fail
   - Consider using environment variables from your hosting provider (Heroku, Railway, etc.)

### 3. Production vs Development

- **Production**: 
  - Turnstile verification is **required**
  - Users must complete the challenge to login or register
  - Both `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET_KEY` must be set
  - If keys are missing, authentication requests will be rejected

- **Development**: 
  - If `ENVIRONMENT=development` and Turnstile keys are not set, verification will be bypassed
  - This is useful for local development when you don't want to set up Turnstile
  - You can still test with Turnstile in development by setting the keys

### 4. Quick Reference: Where to Find Keys

**If you can't find your keys:**
1. Go to Cloudflare Dashboard → Turnstile
2. Click on your widget name
3. Look for a section showing "Site Key" and "Secret Key"
4. Click "Show" or "Reveal" next to the Secret Key if it's hidden
5. Copy both keys

**Note**: The Site Key is always visible, but the Secret Key might be hidden for security. Click the eye icon or "Show" button to reveal it.

### 5. Testing

1. Start your application
2. Navigate to the login or register page
3. You should see the Turnstile widget
4. Complete the challenge before submitting the form

## API Endpoints

- `GET /api/auth/turnstile-site-key` - Returns the Turnstile site key for frontend use

## Notes

- The Turnstile widget automatically resets after successful login/registration
- Tokens are verified server-side before processing authentication requests
- Failed verification will return a 400 error with message "Security verification failed. Please try again."
