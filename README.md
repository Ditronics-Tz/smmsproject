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
git clone https://github.com/yourusername/student-meal-management.git
cd student-meal-management
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
## License
This project is licensed under the MIT License.

## Contributors
- **Your Name** - Developer

For issues and feature requests, please open a GitHub issue.

