# ============================================================================
# Makefile for Django SMMS Project Docker Operations
# ============================================================================
# Provides convenient commands for building, running, and managing the
# Docker containers for both development and production environments
# ============================================================================

.PHONY: help build build-dev build-prod up up-dev up-prod down logs shell migrate makemigrations collectstatic createsuperuser test clean prune

# Colors for output
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "$(GREEN)Available commands:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(NC) %s\n", $$1, $$2}'

build: build-dev ## Build Docker images (default: development)

build-dev: ## Build development Docker images
	@echo "$(GREEN)Building development images...$(NC)"
	docker-compose build --no-cache
	@echo "$(GREEN)Development images built successfully!$(NC)"

build-prod: ## Build production Docker images
	@echo "$(GREEN)Building production images...$(NC)"
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml build --no-cache
	@echo "$(GREEN)Production images built successfully!$(NC)"

up: up-dev ## Start containers (default: development)

up-dev: ## Start development containers
	@echo "$(GREEN)Starting development environment...$(NC)"
	docker-compose up -d
	@echo "$(GREEN)Development environment running at http://127.0.0.1:8000$(NC)"

up-prod: ## Start production containers
	@echo "$(GREEN)Starting production environment...$(NC)"
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
	@echo "$(GREEN)Production environment running at http://127.0.0.1:8000$(NC)"

down: ## Stop and remove containers
	@echo "$(YELLOW)Stopping containers...$(NC)"
	docker-compose down
	@echo "$(GREEN)Containers stopped$(NC)"

down-volumes: ## Stop and remove containers with volumes
	@echo "$(RED)Stopping containers and removing volumes...$(NC)"
	docker-compose down -v
	@echo "$(GREEN)Containers and volumes removed$(NC)"

restart: ## Restart containers
	@echo "$(YELLOW)Restarting containers...$(NC)"
	docker-compose restart
	@echo "$(GREEN)Containers restarted$(NC)"

logs: ## Show container logs
	docker-compose logs -f

logs-web: ## Show web container logs
	docker-compose logs -f web

logs-db: ## Show database container logs
	docker-compose logs -f db

logs-celery: ## Show celery worker logs
	docker-compose logs -f celery

shell: ## Open Django shell in web container
	docker-compose exec web python manage.py shell

bash: ## Open bash shell in web container
	docker-compose exec web bash

db-shell: ## Open PostgreSQL shell
	docker-compose exec db psql -U postgres -d smmsdb

migrate: ## Run database migrations
	@echo "$(GREEN)Running migrations...$(NC)"
	docker-compose exec web python manage.py migrate
	@echo "$(GREEN)Migrations completed$(NC)"

makemigrations: ## Create new migrations
	@echo "$(GREEN)Creating migrations...$(NC)"
	docker-compose exec web python manage.py makemigrations
	@echo "$(GREEN)Migrations created$(NC)"

collectstatic: ## Collect static files
	@echo "$(GREEN)Collecting static files...$(NC)"
	docker-compose exec web python manage.py collectstatic --noinput
	@echo "$(GREEN)Static files collected$(NC)"

createsuperuser: ## Create Django superuser
	docker-compose exec web python manage.py createsuperuser

test: ## Run tests
	@echo "$(GREEN)Running tests...$(NC)"
	docker-compose exec web python manage.py test

check: ## Run Django system checks
	docker-compose exec web python manage.py check

size: ## Show Docker image sizes
	@echo "$(GREEN)Docker image sizes:$(NC)"
	@docker images | grep smmsproject || echo "No images found. Run 'make build' first."

clean: ## Remove all stopped containers and dangling images
	@echo "$(YELLOW)Cleaning up...$(NC)"
	docker-compose down --remove-orphans
	docker system prune -f
	@echo "$(GREEN)Cleanup completed$(NC)"

prune: ## Remove all unused Docker resources (WARNING: destructive)
	@echo "$(RED)WARNING: This will remove ALL unused Docker resources!$(NC)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker system prune -a --volumes -f; \
		echo "$(GREEN)Pruning completed$(NC)"; \
	else \
		echo "$(YELLOW)Pruning cancelled$(NC)"; \
	fi

backup-db: ## Backup database to file
	@echo "$(GREEN)Backing up database...$(NC)"
	docker-compose exec -T db pg_dump -U postgres smmsdb > backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo "$(GREEN)Database backed up$(NC)"

restore-db: ## Restore database from backup file (usage: make restore-db FILE=backup.sql)
	@echo "$(YELLOW)Restoring database from $(FILE)...$(NC)"
	docker-compose exec -T db psql -U postgres -d smmsdb < $(FILE)
	@echo "$(GREEN)Database restored$(NC)"

ps: ## Show running containers
	docker-compose ps

top: ## Show container processes
	docker-compose top

stats: ## Show container resource usage statistics
	docker stats $$(docker-compose ps -q)

# Security scanning
security-scan: ## Scan image for vulnerabilities (requires Docker Scout)
	@echo "$(GREEN)Scanning for security vulnerabilities...$(NC)"
	docker scout cves smmsproject_web:latest || echo "$(YELLOW)Docker Scout not available. Install with: docker scout install$(NC)"

# Development helpers
dev-setup: build-dev up-dev migrate ## Complete development setup
	@echo "$(GREEN)Development environment ready!$(NC)"
	@echo "$(GREEN)Access the application at: http://127.0.0.1:8000$(NC)"

prod-setup: build-prod up-prod ## Complete production setup
	@echo "$(GREEN)Production environment ready!$(NC)"
	@echo "$(GREEN)Access the application at: http://127.0.0.1:8000$(NC)"
