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
- **Version Control & CI/CD:** GitHub Actions

---
## Installation & Setup
### Prerequisites
Ensure you have the following installed:
- Python (>= 3.8)
- Docker & Docker Compose
- PostgreSQL
- Nginx (for production deployment)

### Clone the Repository
```bash
git clone https://github.com/Ditronics-Tz/smmsproject.git
cd smmsproject
```

### Setup Environment Variables
Create a `.env` file in the root directory:
```env
DEBUG=False
SECRET_KEY=your_secret_key
DATABASE_NAME=student_meal_db
DATABASE_USER=postgres
DATABASE_PASSWORD=your_password
DATABASE_HOST=db
DATABASE_PORT=5432
ALLOWED_HOSTS=*
```

### Build and Run with Docker
```bash
docker-compose up --build -d
```

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
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```
Enable the config and restart Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/student_meal /etc/nginx/sites-enabled/
sudo systemctl restart nginx
```

### Running in Production
```bash
docker-compose -f docker-compose.prod.yml up --build -d
```

---
## CI/CD Deployment with GitHub Actions
### Steps to Push to GitHub and Deploy
1. Commit and push changes to GitHub:
   ```bash
   git add .
   git commit -m [write-comment]
   git push origin master
   then merge with main
   ```

2. Set up GitHub Actions workflow (`.github/workflows/deploy.yml`):
   ```yaml
   name: Deploy
   on:
     push:
       branches:
         - main
   jobs:
     deploy:
       runs-on: ubuntu-latest
       steps:
         - name: Checkout code
           uses: actions/checkout@v3
         - name: Deploy to Server
           uses: appleboy/ssh-action@v0.1.7
           with:
             host: ${{ secrets.SERVER_IP }}
             username: ${{ secrets.SERVER_USER }}
             key: ${{ secrets.SSH_PRIVATE_KEY }}
             script: |
               cd /path/to/project
               git pull origin main
               docker-compose -f docker-compose.prod.yml up --build -d
   ```

### Environment Variables in GitHub Secrets
- `SERVER_IP`: Your server's IP address
- `SERVER_USER`: Your SSH username
- `SSH_PRIVATE_KEY`: SSH key for authentication

Once set up, pushing to the `main` branch will automatically deploy the application.

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

### Branding & Visual Identity (optional overrides)

| Env Var | Default | Description | Override |
|---------|---------|-------------|----------|
| `BRAND_NAME` | `Student Meal Management System` | Display name shown in the UI | Set your organization's name |
| `BRAND_LOGO_URL` | *(empty)* | URL for a custom logo image | Set to a publicly accessible URL |
| `BRAND_PRIMARY_COLOR` | *(empty)* | Primary color (hex, e.g. `#2a7ae2`) | Set your brand color |
| `BRAND_CURRENCY` | `Tsh` | Currency display code | Set your currency symbol/Code |
| `SUPPORT_CONTACT` | *(empty)* | Support contact email/phone | Set your support contact information |

> **How to override without touching code:**
> 1. Copy `.env.example` to `.env`
> 2. Set each variable for your organization
> 3. Run `docker-compose up --build -d` (or `make prod-setup`)
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
BRAND_NAME=Your Organization Name
BRAND_CURRENCY=USD
SUPPORT_CONTACT=support@your-org.com
```

---
## License
This project is licensed under the MIT License.

## Contributors
- **Your Name** - Developer

For issues and feature requests, please open a GitHub issue.

