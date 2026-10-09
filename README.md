# Student Meal Management System

A web service for managing student meals, built with Django and PostgreSQL. This system allows students to manage meal plans, view menus, and track their meal usage.

## Features
- User authentication and role-based access (students, admins, staff)
- Meal plan management
- Menu tracking and scheduling
- Reports and analytics

## Technologies Used
- **Backend:** Django, Django REST Framework
- **Database:** PostgreSQL
- **Containerization & Deployment:** Docker, Nginx, Gunicorn
- **Version Control:** Git

---
## Installation & Setup
### Prerequisites
Ensure you have Docker Engine and the Docker Compose v2 plugin installed.
For local development without containers, use the Python version in
`Containerfile` plus PostgreSQL and Redis.

### Clone the Repository
```bash
git clone https://github.com/Ditronics-Tz/smmsproject.git
cd smmsproject
```

### Setup Environment Variables
Copy the checked-in template, then replace the sample secrets and hostnames.
The Compose stack reads `DB_*` (not `DATABASE_*`) and requires both
`SECRET_KEY` and `DB_PASSWORD`:
```env
```
```bash
cp .env.example .env
```
For a local Docker run, keep `DB_HOST=db` and set `ALLOWED_HOSTS` to
`localhost,127.0.0.1`. Do not use `ALLOWED_HOSTS=*`.

### Build and Run with Docker
```bash
docker compose up --build -d
```

The first start applies database migrations through the container entrypoint.
To inspect startup or troubleshoot, run `docker compose logs -f web`.

The application should now be running on `http://localhost:8000/`.

---
## Deployment with Nginx and Gunicorn
### Setup Server
Ensure your server has:
- Docker & Docker Compose installed
- Nginx installed

### Configure Nginx
Create an Nginx config file (`/etc/nginx/sites-available/student_meal`):
```nginx
server {
    listen 80;
    server_name your_domain_or_ip;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        # This single trusted Nginx edge overwrites any client-supplied value.
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
Set `NUM_PROXIES=1` in `.env` for this topology. If requests pass through
multiple trusted proxies, configure each proxy to preserve the verified chain
and set `NUM_PROXIES` to the count represented in `X-Forwarded-For`. Never set
it above zero when clients can reach Django directly or inject forwarding
headers unless the trusted edge overwrites them before forwarding.
Enable the config and restart Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/student_meal /etc/nginx/sites-enabled/
sudo systemctl restart nginx
```

### Running in Production
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

---
## Manual verification and deployment

This repository currently has no CI/CD workflows. Before merging or deploying,
run the checks locally and review their results:

```bash
python manage.py test smmsapp.tests
make schema
git diff --exit-code -- docs/openapi.yaml
pip-audit -r requirements.txt --no-deps
```

Deploy manually from the server after reviewing and merging the intended commit:

```bash
git pull --ff-only origin main
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

---
## API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/login/` | POST | User login |
| `/api/meals/` | GET | List meals |
| `/api/meals/{id}/` | GET | Get meal details |
| `/api/meals/` | POST | Add new meal (admin only) |

---
## Deploying for a new organization

This section documents every environment variable required to deploy the SMMS system for a new organization. None of these require code changes — all are read from the environment via `os.getenv()` with sensible defaults.

### Core Django settings

| Env Var | Default | Description | Override |
|---------|---------|-------------|----------|
| `DEBUG` | `False` | Turn on for local development only | Set to `True` for dev |
| `SECRET_KEY` | *(required)* | Django's secret key — **must be set per deployment** | Generate a new strong value |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated list of allowed hosts | Add your domain(s), e.g. `example.com,www.example.com` |
| `API_BASE_URL` | `http://127.0.0.1:8000` | Base URL for the API (used in email links, etc.) | Set to your public URL, e.g. `https://app.your-org.com` |
| `INVITE_TOKEN_TTL_HOURS` | `48` | Password-invite token validity period in hours | Set the desired invite expiry window |

### Database

| Env Var | Default | Description | Override |
|---------|---------|-------------|----------|
| `DB_NAME` | `smmsdb` | Database name | Set to your database name |
| `DB_USER` | `postgres` | Database user | Set to your DB user |
| `DB_PASSWORD` | *(required)* | Database password — **must be set per deployment** | Generate a secure password |
| `DB_HOST` | `db` | Database host (Docker network hostname) | Change if not using Docker Compose |
| `DB_PORT` | `5432` | Database port | Set to your PostgreSQL port |

### CORS & CSRF

| Env Var | Default | Description | Override |
|---------|---------|-------------|----------|
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://localhost:3001` | Comma-separated origins allowed for CORS | Add your frontend domain(s) |
| `CSRF_TRUSTED_ORIGINS` | *(empty)* | Comma-separated origins trusted for CSRF | Add your frontend domain(s) |

### HTTPS / Security Headers

| Env Var | Default | Description | Override |
|---------|---------|-------------|----------|
| `SECURE_SSL_REDIRECT` | `False` | Redirect HTTP → HTTPS (set `True` only if the app terminates TLS) | Set `True` behind a reverse proxy that handles HTTPS |
| `SECURE_HSTS_SECONDS` | *(empty)* | HSTS seconds — enable for HTTPS enforcement | e.g. `31536000` for 1 year |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | `True` | Include subdomains in HSTS | Set `False` if needed |
| `SECURE_HSTS_PRELOAD` | `True` | Add HSTS to browser preload list | Set `False` if needed |

### Firebase (FCM push notifications — optional)

| Env Var | Default | Description | Override |
|---------|---------|-------------|----------|
| `FIREBASE_API_KEY` | *(empty)* | Firebase API key | Get from Firebase console |
| `FIREBASE_SENDER_ID` | *(empty)* | Firebase sender ID | Get from Firebase console |
| `FIREBASE_PROJECT_ID` | *(empty)* | Firebase project ID | Get from Firebase console |
| `FIREBASE_SERVICE_ACCOUNT_FILE` | *(unset)* | Optional path to service-account JSON for push tasks | Configure only when using Firebase push |

### Email (outgoing email notifications)

| Env Var | Default | Description | Override |
|---------|---------|-------------|----------|
| `EMAIL_HOST` | `smtp.gmail.com` | SMTP host | Change if using a different email provider |
| `EMAIL_HOST_USER` | *(empty)* | Email username | Set your email address |
| `EMAIL_HOST_PASSWORD` | *(empty)* | Email password — **required for Gmail/SMTP** | Generate an app password for Gmail or use your SMTP credentials |
| `DEFAULT_FROM_EMAIL` | *(empty)* | Default sender email | Set your organization's email |

### Celery (background task queue)

| Env Var | Default | Description | Override |
|---------|---------|-------------|----------|
| `CELERY_BROKER_URL` | `redis://redis:6379/0` | Celery broker URL | Change if using a different broker or host |
| `CELERY_RESULT_BACKEND` | *(same as broker)* | Celery result backend | Set explicitly if different from broker |

### Optional: Superuser creation (development only)

| Env Var | Default | Description | Override |
|---------|---------|-------------|----------|
| `DJANGO_SUPERUSER_USERNAME` | `admin` | Username for auto-created superuser | Set your preferred username (dev only) |
| `DJANGO_SUPERUSER_EMAIL` | `admin@smms.local` | Email for auto-created superuser | Set your email (dev only) |
| `DJANGO_SUPERUSER_PASSWORD` | `Admin123!` | Password for auto-created superuser | Set your password (dev only) |

### Feature, operations, and preorder settings

These optional variables are also read by Django settings. Leave the example
values in place unless the deployment needs a different policy.

| Env Var | Default | Description |
|---------|---------|-------------|
| `NUM_PROXIES` | `0` | Trusted reverse-proxy hops; only raise when the edge overwrites forwarding headers |
| `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` | `True` | Send session/CSRF cookies over HTTPS only |
| `CELERY_TIMEZONE` | `Africa/Dar_es_Salaam` | Timezone used by scheduled jobs |
| `MENU_ENFORCED`, `STOCK_ENFORCED` | `False` | Enforce menu availability and stock checks |
| `SPONSOR_FALLBACK_TO_WALLET` | `True` | Allow wallet fallback when sponsorship does not cover an item |
| `RFID_BALANCE_FLOOR` | `-500.00` | Lowest permitted wallet balance |
| `PENALTY_FEE`, `STRIKE_LIMIT`, `STRIKE_RESET_ON_DEPOSIT` | `500.00`, `10`, `False` | Strike and insufficient-balance penalty policy |
| `SCAN_THROTTLE_RATE` | `120` | Maximum scans per operator per minute |
| `AUDIT_RETENTION_DAYS` | `365` | Audit-log retention period |
| `SMS_PROVIDER` | `log` | SMS adapter: `log`, `twilio`, or `beem` |
| `SMS_DAILY_LIMIT`, `SMS_MONTHLY_LIMIT` | `3`, `10000` | SMS sending limits |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | unset | Twilio credentials/sender; needed only with Twilio |
| `BEEM_API_KEY`, `BEEM_SECRET_KEY`, `BEEM_SENDER_ID` | unset, unset, `SMMS` | Beem credentials/sender; needed only with Beem |
| `PREORDER_TIME_ZONE`, `PREORDER_CUTOFF_TIME` | `Africa/Dar_es_Salaam`, `18:00` | Local timezone and previous-day preorder cutoff |
| `PREORDER_MAX_DAYS_AHEAD`, `PREORDER_MAX_QTY_PER_ITEM` | `1`, `1` | Preorder horizon and per-item quantity cap |
| `PREORDER_NOSHOW_FEE`, `PREORDER_REMINDER_ENABLED` | `0.00`, `False` | No-show fee and optional reminder toggle |
| `FEATURES_DEFAULT` | `{}` | JSON object of deployment-level feature defaults |

The `SCHOOL_SYSTEM_*` variables configure the optional CSV integration adapter;
their full list and sync schedule are documented in `.env.example` and
[`docs/integrations.md`](docs/integrations.md).

### Branding & Visual Identity (optional overrides)

| Env Var | Default | Description | Override |
|---------|---------|-------------|----------|
| `APP_NAME`, `APP_SHORT_NAME` | `Student Meal Management System`, `SMMS` | Public application names | Set the organization/product name |
| `CURRENCY_CODE`, `CURRENCY_SYMBOL`, `CURRENCY_DECIMALS` | `TZS`, `TSh`, `2` | Public currency formatting | Set the deployment currency |
| `APP_LOCALE` | `en-TZ` | Locale advertised by public config | Set the desired locale |

> **How to override without touching code:**
> 1. Copy `.env.example` to `.env`
> 2. Replace the required sample secrets and set host/origin values for your organization
> 3. Run `docker compose up --build -d` (or `make prod-setup`)
> 4. All changes are purely environment-driven — no Python files need modification

### Example `.env` for a new organization

```env
# Core
DEBUG=False
SECRET_KEY=your_strong_secret_key_here
ALLOWED_HOSTS=your-domain.com,www.your-domain.com
API_BASE_URL=https://app.your-org.com

# Database
DB_NAME=your_db_name
DB_USER=your_db_user
DB_PASSWORD=your_secure_db_password
DB_HOST=db
DB_PORT=5432

# CORS / CSRF
CORS_ALLOWED_ORIGINS=https://your-domain.com,https://www.your-domain.com
CSRF_TRUSTED_ORIGINS=https://your-domain.com,https://www.your-domain.com

# HTTPS
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000

# Email
EMAIL_HOST=smtp.sendgrid.net
EMAIL_HOST_USER=your_sendgrid_user
EMAIL_HOST_PASSWORD=your_sendgrid_password

# Branding
APP_NAME=Your Organization Name
APP_SHORT_NAME=Your App
CURRENCY_CODE=TZS
CURRENCY_SYMBOL=TSh
APP_LOCALE=en-TZ
```

---
## License
This project is licensed under the MIT License.

## Contributors
- **Your Name** - Developer

For issues and feature requests, please open a GitHub issue.

