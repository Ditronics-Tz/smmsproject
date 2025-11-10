#!/bin/bash
# ============================================================================
# Docker Build Script for SMMS Project
# ============================================================================
# This script builds Docker images for both development and production
# ============================================================================

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}SMMS Project Docker Build Script${NC}"
echo -e "${GREEN}========================================${NC}"

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed${NC}"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}Error: Docker Compose is not installed${NC}"
    exit 1
fi

# Parse command line arguments
ENVIRONMENT=${1:-dev}
NO_CACHE=${2:-}

if [ "$ENVIRONMENT" != "dev" ] && [ "$ENVIRONMENT" != "prod" ]; then
    echo -e "${RED}Error: Invalid environment. Use 'dev' or 'prod'${NC}"
    echo "Usage: $0 [dev|prod] [--no-cache]"
    exit 1
fi

# Build arguments
BUILD_ARGS=""
if [ "$NO_CACHE" == "--no-cache" ]; then
    BUILD_ARGS="--no-cache"
fi

echo -e "${YELLOW}Building ${ENVIRONMENT} environment...${NC}"

# Build based on environment
if [ "$ENVIRONMENT" == "dev" ]; then
    echo -e "${GREEN}Building development images...${NC}"
    docker-compose build $BUILD_ARGS
    
    echo -e "${GREEN}Development build complete!${NC}"
    echo -e "${YELLOW}To start the environment, run:${NC}"
    echo -e "  docker-compose up -d"
    echo -e "  or"
    echo -e "  make up-dev"
else
    echo -e "${GREEN}Building production images...${NC}"
    docker-compose -f docker-compose.yml -f docker-compose.prod.yml build $BUILD_ARGS
    
    echo -e "${GREEN}Production build complete!${NC}"
    echo -e "${YELLOW}To start the environment, run:${NC}"
    echo -e "  docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
    echo -e "  or"
    echo -e "  make up-prod"
fi

# Show image sizes
echo ""
echo -e "${GREEN}Image sizes:${NC}"
docker images | grep smmsproject || echo "No images found."

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Build completed successfully!${NC}"
echo -e "${GREEN}========================================${NC}"
