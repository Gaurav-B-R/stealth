# Developer Emails Management Guide

This guide explains how to manage developer email accounts in the database.

## Database Table: `developer_emails`

The `developer_emails` table stores email addresses that are allowed to bypass university domain validation.

### Table Structure:
- `email` (VARCHAR, PRIMARY KEY) - The specific email address
- `university_name` (VARCHAR) - University name to auto-fill (default: "Developer Account (Testing)")

## How to Add Developer Emails

### Option 1: Using psql (PostgreSQL Command Line)

1. Connect to your database:
   ```bash
   psql -h your_host -U your_username -d your_database
   ```

2. Run the SQL command:
   ```sql
   INSERT INTO developer_emails (email, university_name) 
   VALUES ('newdeveloper@example.com', 'Developer Account (Testing)')
   ON CONFLICT (email) DO NOTHING;
   ```

### Option 2: Using pgAdmin or Database GUI

1. Open your database management tool (pgAdmin, DBeaver, etc.)
2. Connect to your database
3. Open SQL Query Editor
4. Run:
   ```sql
   INSERT INTO developer_emails (email, university_name) 
   VALUES ('newdeveloper@example.com', 'Developer Account (Testing)')
   ON CONFLICT (email) DO NOTHING;
   ```

### Option 3: Using the SQL File

1. Edit `add_developer_emails.sql` and add your emails
2. Run it:
   ```bash
   psql -h your_host -U your_username -d your_database -f add_developer_emails.sql
   ```

## SQL Commands Reference

### Add a Single Developer Email
```sql
INSERT INTO developer_emails (email, university_name) 
VALUES ('developer@example.com', 'Developer Account (Testing)')
ON CONFLICT (email) DO NOTHING;
```

### Add Multiple Developer Emails at Once
```sql
INSERT INTO developer_emails (email, university_name) 
VALUES 
    ('developer1@example.com', 'Developer Account (Testing)'),
    ('developer2@example.com', 'Developer Account (Testing)'),
    ('developer3@example.com', 'Developer Account (Testing)')
ON CONFLICT (email) DO NOTHING;
```

### View All Developer Emails
```sql
SELECT * FROM developer_emails;
```

### Remove a Developer Email
```sql
DELETE FROM developer_emails WHERE email = 'developer@example.com';
```

### Update University Name for a Developer Email
```sql
UPDATE developer_emails 
SET university_name = 'Custom Developer Name' 
WHERE email = 'developer@example.com';
```

## Important Notes

1. **Specific Emails Only**: Add the full email address, not just the domain
   - ✅ Correct: `developer@example.com`
   - ❌ Wrong: `example.com`

2. **Case Insensitive**: Emails are stored in lowercase, but you can enter them in any case

3. **ON CONFLICT**: The `ON CONFLICT (email) DO NOTHING` clause prevents errors if the email already exists

4. **University Name**: This will be auto-filled when the developer registers. You can customize it per email if needed.

## Example: Adding Your Team's Developer Emails

```sql
INSERT INTO developer_emails (email, university_name) 
VALUES 
    ('developer1@yourcompany.com', 'Developer Account (Testing)'),
    ('developer2@yourcompany.com', 'Developer Account (Testing)'),
    ('qa@yourcompany.com', 'QA Testing Account')
ON CONFLICT (email) DO NOTHING;
```

## Security Note

- Only add trusted developer emails
- Regularly review and remove developer emails that are no longer needed
- In production, consider adding an `is_active` flag to easily enable/disable developer accounts
