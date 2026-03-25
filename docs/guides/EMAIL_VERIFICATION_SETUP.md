# Email Verification Setup Guide

This guide will help you set up email verification using Resend.com for your Rilono application.

## Step 1: Install Dependencies

The Resend SDK has already been added to `requirements.txt`. Install it by running:

```bash
pip install -r requirements.txt
```

Or install Resend directly:

```bash
pip install resend==2.4.0
```

## Step 2: Create Resend.com Account

1. Go to [https://resend.com](https://resend.com)
2. Sign up for a free account (you get 3,000 emails/month free)
3. Verify your email address

## Step 3: Add Your Domain (rilono.com)

1. In the Resend dashboard, go to **Domains**
2. Click **Add Domain**
3. Enter `rilono.com`
4. Resend will provide you with DNS records to add:
   - **SPF Record**: Add to your DNS
   - **DKIM Records**: Add to your DNS
   - **DMARC Record** (optional but recommended): Add to your DNS

5. Add these records to your domain's DNS settings (wherever you manage your domain)
6. Wait for DNS propagation (can take a few minutes to 24 hours)
7. Once verified, your domain status will show as "Verified"

## Step 4: Create API Key

1. In Resend dashboard, go to **API Keys**
2. Click **Create API Key**
3. Give it a name (e.g., "Rilono Production")
4. Copy the API key (you'll only see it once!)

## Step 5: Configure Environment Variables

Add the following to your `.env` file:

```env
# Resend Email Configuration
RESEND_API_KEY=re_your_api_key_here
RESEND_FROM_EMAIL=noreply@rilono.com
RESEND_FROM_NAME=Rilono

# Application Base URL (for verification links)
BASE_URL=https://yourdomain.com
# For local development, use:
# BASE_URL=http://localhost:8000

# Development Mode (uses Resend test email - no domain verification needed)
USE_TEST_EMAIL=true
# This allows you to test emails without verifying your domain
# Emails will be sent from delivered@resend.dev (Resend's test sender)
```

**Important Notes:**
- Replace `re_your_api_key_here` with your actual Resend API key
- The `RESEND_FROM_EMAIL` must be from your verified domain (rilono.com)
- Update `BASE_URL` to your production domain when deploying

## Step 6: Test Email Verification

1. Start your server:
   ```bash
   uvicorn app.main:app --reload
   ```

2. Register a new account with a valid university email
3. Check your email inbox for the verification email
4. Click the verification link
5. Try logging in

## Step 7: Database Migration

Since we added new fields to the User model, you need to create a migration:

**Option A: Using Alembic (Recommended)**
```bash
# Install Alembic if not already installed
pip install alembic

# Initialize Alembic (if not already done)
alembic init alembic

# Create a migration
alembic revision --autogenerate -m "Add email verification fields"

# Apply the migration
alembic upgrade head
```

**Option B: Manual SQL (Quick fix for development)**
```sql
ALTER TABLE users 
ADD COLUMN email_verified BOOLEAN DEFAULT FALSE,
ADD COLUMN verification_token VARCHAR UNIQUE,
ADD COLUMN verification_token_expires TIMESTAMP;
```

## API Endpoints

### Verify Email
```
GET /api/auth/verify-email?token=<verification_token>
```

### Resend Verification Email
```
POST /api/auth/resend-verification
Body: { "email": "user@university.edu" }
```

## Features Implemented

✅ Email verification on registration
✅ Beautiful HTML email template
✅ Token expiration (24 hours)
✅ Resend verification email functionality
✅ Login blocked until email verified
✅ Frontend verification page
✅ Automatic redirect after registration

## Troubleshooting

### Emails not sending?
1. Check that `RESEND_API_KEY` is set correctly in `.env`
2. Verify your domain is verified in Resend dashboard
3. Check Resend dashboard for error logs
4. Ensure `RESEND_FROM_EMAIL` uses your verified domain

### Verification link not working?
1. Check that `BASE_URL` is set correctly
2. Ensure the token hasn't expired (24 hours)
3. Check server logs for errors

### Domain verification issues?
1. Wait for DNS propagation (can take up to 24 hours)
2. Use DNS checker tools to verify records are set correctly
3. Contact Resend support if issues persist

## Production Checklist

- [ ] Domain verified in Resend
- [ ] API key added to production environment variables
- [ ] `BASE_URL` set to production domain
- [ ] Database migration applied
- [ ] Test email verification flow
- [ ] Monitor Resend dashboard for email delivery rates

## Support

- Resend Documentation: https://resend.com/docs
- Resend Support: support@resend.com
