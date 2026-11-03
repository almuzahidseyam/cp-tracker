# CP Tracker

Track saved competitive-programming statistics across Codeforces, LeetCode, CodeChef and AtCoder, with an email-code login and a friends leaderboard. Dashboard visits read stored snapshots; refresh is explicit and cached. Platform APIs can be unavailable or delayed. This is a small self-hosted application, not a guaranteed real-time or turnkey production service.

## Local setup

Python 3.12+ is required. In PowerShell:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(50))"
# Put that random value in SECRET_KEY; keep DEBUG=True for loopback development.
# Configure SMTP, or explicitly set ALLOW_CONSOLE_EMAIL=True for a local demo.
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py runserver 127.0.0.1:8000
```

On macOS/Linux use `.venv/bin/python`. Console email is allowed only with both `DEBUG=True` and `ALLOW_CONSOLE_EMAIL=True`. Otherwise missing SMTP configuration disables email login; codes are not silently written into production logs. Set `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and `DEFAULT_FROM_EMAIL` for SMTP with TLS. Never reuse the previous checked-in Django secret.

The local stylesheet is committed, so Node is needed only after editing templates/styles: `npm ci` then `npm run build:css`. There are no runtime CDN scripts or Google Fonts on the login page.

## Login behavior

- Codes expire after five minutes, allow five attempts and can succeed only once. Each challenge is tied to the requesting browser session. Only a keyed digest is stored; consuming a code clears it.
- A new code invalidates earlier challenges. Sending has a one-minute per-account cooldown, a five-attempt hourly email budget and a twenty-attempt hourly source-IP budget, shared through the database.
- Successful login rotates the session. Disabled established accounts are never activated by entering an OTP. Staff can manage account activation in Django admin; admin changes lock the activation policy. `createsuperuser` creates administrative access.
- Email delivery errors invalidate the challenge. Normalization permits case-insensitive lookup; ambiguous legacy accounts that differ only by email case require operator reconciliation.

The IP budget uses `REMOTE_ADDR`, never arbitrary forwarded headers. Users sharing a proxy/NAT share this limit; configure a trusted client-IP integration and edge abuse controls for a public deployment. OTP email is not phishing-resistant MFA. Run `python manage.py purge_auth_state` daily to remove expired challenges and old budget records.

## Handles and statistics

Handle updates fetch and validate the new public profile before changing the saved handle. A failed lookup preserves the previous handle, totals and activity. A valid zero-solve account clears stale activity from the previous handle. Refresh cannot resurrect a deleted handle or overwrite a concurrent handle change. Checking a public profile **does not prove ownership** of that external account.

Codeforces/LeetCode can include recent accepted submissions. CodeChef uses a page counter and treats an unrecognized page as unavailable. AtCoder uses the [AtCoder Problems aggregate accepted count](https://github.com/kenkoooo/AtCoderProblems/blob/master/doc/api.md), not the first page of submissions; its recent activity is not fetched. Streak fields are not implemented as a reliable feature. Counts are summed across platforms and do not deduplicate equivalent problems. Leaderboard search requires an exact email, and totals do not multiply when an account has several followers.

Each user has ten handle-update attempts and five refresh attempts per hour. Statistics are cached for an hour. The cache is per process; login and request limits are database-backed. The application has bounded network socket timeouts, not a hard overall refresh deadline; large refresh jobs need a background worker for production scale.

## Scheduled refresh

Set a separate random `CRON_SECRET` of at least 32 ASCII characters. Call `/api/cron/refresh/` using `Authorization: Bearer <secret>`. The previous query-string token and known fallback are rejected. GET and POST are supported for scheduler compatibility. Each call handles at most 20 records and returns `next_cursor`; continue with `?after=<cursor>` after at least one minute. Missing configuration disables the endpoint. A long batch may exceed short serverless request limits; do not assume the Vercel example removes that restriction.

## Upgrade and deployment

Back up the database and set a new secret before `migrate`. Migration 0006 removes old plaintext OTPs, creates challenge/budget tables and preserves each existing account's active/inactive state by locking activation. Existing inactive registrations therefore require an operator decision before reuse. Existing sessions are invalidated when the Django secret changes. No email is sent by the migration.

For local containers set an alphanumeric `POSTGRES_PASSWORD` in `.env`, then `docker compose up --build`. Ports bind to loopback; PostgreSQL is not exposed. Use an external persistent PostgreSQL database for serverless deployments. Run migrations as a controlled release step and back up the database. Public deployment requires HTTPS, `DEBUG=False`, explicit allowed hosts, working SMTP, trusted proxy configuration, edge rate limits and monitoring. HSTS subdomains/preload remain operator decisions. Repository updates do not modify a hosted database or email configuration automatically.

## Verification

```sh
python manage.py test
python manage.py makemigrations --check --dry-run
npm run build:css
```

CI runs the regression suite on Windows/Linux and PostgreSQL, including two concurrent attempts to consume one OTP. Mail tests use an in-memory backend; platform responses use fixtures. Browser checks use a local mail sink and fixture statistics. No real email is sent during verification. MIT licensed.
