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

# Функция для остановки по паттерну
stop_by_pattern() {
    local name=$1
    local pattern=$2
    
    echo -e "${BLUE}🔍 Ищу процессы $name...${NC}"
    if pgrep -f "$pattern" > /dev/null; then
        pkill -f "$pattern"
        echo -e "${GREEN}✅ $name остановлен${NC}"
    else
        echo -e "${RED}⚠️ Процессы $name не найдены${NC}"
    fi
}

# Останавливаем конкретные сервисы
stop_by_pattern "Celery Workers" "celery -A app.celery_app worker"
stop_by_pattern "Celery Beat" "celery -A app.celery_app beat"
stop_by_pattern "Flower" "celery -A app.celery_app flower"
stop_by_pattern "FastAPI (Uvicorn)" "uvicorn main:app"

# Финальная зачистка (на всякий случай)
echo -e "${BLUE}🧹 Проверяю оставшиеся процессы...${NC}"
if pgrep -f "celery" > /dev/null; then
    echo -e "${BLUE}🔪 Принудительно завершаю остатки...${NC}"
    pkill -f "celery" || true
fi

# Удаляем старые PID файлы, если они есть (для очистки мусора)
rm -f logs/*.pid

echo -e "${GREEN}🏁 Все сервисы остановлены${NC}"

