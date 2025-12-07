#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

HOST_VAL=${MYSQL_HOST:-"localhost"}
PORT_VAL=${MYSQL_PORT:-3306}

wait_for_service() {
    local host=$1
    local port=$2
    local service_name=$3
    local max_attempts=60
    local attempt=0
    
    echo -e "${YELLOW}Waiting for $service_name at $host:$port...${NC}"
    
    while [ $attempt -lt $max_attempts ]; do
        python -c "import socket, sys; s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(5); sys.exit(0 if s.connect_ex(('$host', int('$port'))) == 0 else 1)"
        
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓ $service_name is reachable!${NC}"
            return 0
        fi
        
        attempt=$((attempt + 1))
        echo -e "  Attempt $attempt/$max_attempts..."
        sleep 2
    done
    
    echo -e "${RED}✗ Failed to connect to $service_name ($host:$port) after $max_attempts attempts${NC}"
    return 1
}

echo -e "${BLUE}Checking service dependencies...${NC}"
echo ""

wait_for_service "$HOST_VAL" "$PORT_VAL" "External MySQL" || exit 1

echo -e "${YELLOW}Waiting for databases to fully initialize...${NC}"
sleep 2

echo ""
echo -e "${BLUE}Running database migrations...${NC}"
echo ""

cd /app

echo -e "${YELLOW}Generating migrations...${NC}"
python manage.py makemigrations || {
    echo -e "${RED}✗ Failed to generate migrations${NC}"
    exit 1
}
echo -e "${GREEN}✓ Migrations generated${NC}"
echo ""

echo -e "${YELLOW}Running MySQL migrations...${NC}"
python manage.py migrate || {
    echo -e "${RED}✗ Failed to run MySQL migrations${NC}"
    exit 1
}
echo -e "${GREEN}✓ MySQL migrations completed${NC}"
echo ""

if [ "$CREATE_SUPERUSER" = "true" ]; then
    echo -e "${YELLOW}Creating Django superuser...${NC}"
    python manage.py createsuperuser --noinput --username admin --email admin@example.com 2>/dev/null || true
    echo -e "${GREEN}✓ Superuser creation step finished${NC}"
    echo ""
fi

exec "$@"