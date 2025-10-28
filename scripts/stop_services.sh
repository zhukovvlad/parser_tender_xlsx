#!/bin/bash
# scripts/stop_services.sh

#
# Скрипт для остановки всех сервисов проекта.
#

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🛑 Stopping Tender Parser Services${NC}"

# Функция для остановки сервиса по PID файлу
stop_service() {
    local name=$1
    local pidfile="logs/${name}.pid"
    
    if [ -f "$pidfile" ]; then
        local pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            echo -e "${BLUE}🛑 Останавливаю $name (PID: $pid)...${NC}"
            kill "$pid"
            rm "$pidfile"
            echo -e "${GREEN}✅ $name остановлен${NC}"
        else
            echo -e "${RED}⚠️ Процесс $name (PID: $pid) уже не активен${NC}"
            rm "$pidfile"
        fi
    else
        echo -e "${RED}⚠️ PID файл для $name не найден${NC}"
    fi
}

# Останавливаем сервисы
stop_service "celery-worker"
stop_service "celery-beat"
stop_service "flower"

# Останавливаем все Celery процессы (на всякий случай)
echo -e "${BLUE}🧹 Очищаю оставшиеся Celery процессы...${NC}"
pkill -f "celery" || true

# Показываем оставшиеся процессы
if pgrep -f "celery" > /dev/null; then
    echo -e "${RED}⚠️ Обнаружены активные Celery процессы:${NC}"
    pgrep -f "celery" | head -5
else
    echo -e "${GREEN}✅ Все Celery процессы остановлены${NC}"
fi

echo -e "${GREEN}🏁 Все сервисы остановлены${NC}"
