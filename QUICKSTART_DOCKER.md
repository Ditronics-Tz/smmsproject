# Quick Start Guide - Docker for SMMS Project

## 🚀 Get Started in 3 Steps

### 1. Setup Environment
```bash
cp .env.example .env
nano .env  # Edit with your settings
```

### 2. Build & Start
```bash
# Development
make dev-setup

# Production
make prod-setup
```

### 3. Access Application
- Development: http://127.0.0.1:8000
- Admin: http://127.0.0.1:8000/admin

---

## 📚 Key Commands

### Development
```bash
make up-dev          # Start dev environment
make down            # Stop all containers
make logs-web        # View web logs
make shell           # Django shell
make migrate         # Run migrations
make createsuperuser # Create admin user
```

### Production
```bash
make build-prod      # Build prod images
make up-prod         # Start prod environment
make backup-db       # Backup database
```

### Monitoring
```bash
make ps              # Show containers
make stats           # Resource usage
make logs            # All logs
```

---

## 📖 Full Documentation

- **README_DOCKER.md** - Complete guide with diagrams and troubleshooting
- **DOCKER_VALIDATION.md** - Validation report and configuration details
- **Makefile** - Run `make help` for all commands

---

## 🔧 Configuration Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage optimized build |
| `docker-compose.yml` | Development environment |
| `docker-compose.prod.yml` | Production overrides |
| `entrypoint.sh` | Startup script |
| `.dockerignore` | Build optimization |
| `.env.example` | Environment template |
| `Makefile` | Convenient commands |

---

## 🎯 Key Features

✅ Image size < 200MB  
✅ Localhost-only binding (127.0.0.1:8000)  
✅ Non-root user security  
✅ Hot-reload in development  
✅ Gunicorn in production  
✅ Automated migrations  
✅ Static file handling  
✅ PostgreSQL + Redis  
✅ Celery workers  

---

## 🆘 Troubleshooting

**Port already in use?**
```bash
make down
# Or change port in .env
```

**Permission errors?**
```bash
sudo chown -R $USER:$USER .
make down-volumes
make build-dev
```

**Database issues?**
```bash
make logs-db
make restart
```

---

## 📞 Need Help?

See **README_DOCKER.md** for comprehensive documentation including:
- Architecture diagrams
- Detailed troubleshooting
- Security best practices
- Migration guides
- Performance optimization

---

**Ready to deploy!** 🎉
