#!/bin/bash
# scripts/common.sh
# Общие функции для скриптов запуска сервисов

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Функция для запуска сервиса в фоне
start_service() {
    local name=$1
    local command=$2
    local logfile=$3
    
    echo -e "${BLUE}🚀 Запускаю $name...${NC}"
    nohup $command > "$logfile" 2>&1 &
    local pid=$!
    echo -e "${GREEN}✅ $name запущен (PID: $pid)${NC}"
}
