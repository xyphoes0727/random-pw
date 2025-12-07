#!/bin/sh
cd "$(dirname "$0")"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

ACTION=${1:-up}

case $ACTION in
    up)
        print_status "Starting all services"
        docker compose build
        docker compose up -d
        
        echo ""
        print_status "Waiting for services to be healthy"
        sleep 10
        
        echo ""
        print_success "All services started!"
        docker compose ps
        ;;
    
    down)
        print_status "Stopping all services"
        docker compose down
        print_success "All services stopped!"
        ;;
    
    clean)
        print_warning "This will remove all containers, volumes, and data!"
        read -p "Are you sure? (yes/no): " confirm
        if [ "$confirm" = "yes" ]; then
            print_status "Cleaning up..."
            docker compose down -v
            print_success "Cleanup complete!"
        else
            print_status "Cleanup cancelled."
        fi
        ;;
    
    restart)
        print_status "Restarting all services"
        docker compose restart
        print_success "Services restarted!"
        ;;
    
    logs)
        SERVICE=${2:-}
        if [ -z "$SERVICE" ]; then
            docker compose logs -f
        else
            docker compose logs -f "$SERVICE"
        fi
        ;;
    
    status)
        docker compose ps
        ;;
    
    simulate-ws)
        CSV_PATH=${2:-"data/test_paysim.csv"}
        RATE=${3:-10}
        
        CSV_FILENAME=$(basename "$CSV_PATH")
        
        HOST_FILE_PATH="../data/$CSV_FILENAME"
        
        if [ ! -f "$HOST_FILE_PATH" ]; then
            print_error "File not found: $HOST_FILE_PATH"
            print_warning "Make sure the file is in the 'data' folder at the project root."
            exit 1
        fi

        print_status "Checking dependencies inside fraud_ingest_api"
        docker compose exec fraud-ingest-api pip install websockets pandas > /dev/null 2>&1

        print_status "Starting WebSocket simulation"
        print_status "File: $CSV_FILENAME"
        print_status "Rate: $RATE tx/s"
        

        docker compose exec fraud-ingest-api python manage.py simulate_ws \
            --file "/app/data/$CSV_FILENAME" \
            --rate "$RATE" \
            --url "ws://localhost:8000/ws/transactions/"
        ;;
esac