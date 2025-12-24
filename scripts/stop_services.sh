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
        sleep 1
        
        # Проверяем, остановились ли процессы
        if pgrep -f "$pattern" > /dev/null; then
            echo -e "${RED}⚠️ $name не остановились, принудительное завершение...${NC}"
            pkill -9 -f "$pattern" || true
            sleep 1
        fi
        
        # Финальная проверка
        if pgrep -f "$pattern" > /dev/null; then
            echo -e "${RED}❌ $name всё ещё работают!${NC}"
            return 1
        else
            echo -e "${GREEN}✅ $name остановлен${NC}"
            return 0
        fi
    else
        echo -e "${RED}⚠️ Процессы $name не найдены${NC}"
        return 0
    fi
}

# Останавливаем конкретные сервисы
stop_by_pattern "Celery Workers" "celery -A app.celery_app worker" || true
stop_by_pattern "Celery Beat" "celery -A app.celery_app beat" || true
stop_by_pattern "Flower" "celery -A app.celery_app flower" || true
stop_by_pattern "FastAPI (Uvicorn)" "uvicorn main:app" || true

# Финальная зачистка (на всякий случай)
echo -e "${BLUE}🧹 Проверяю оставшиеся процессы...${NC}"
if pgrep -f "celery -A app.celery_app" > /dev/null; then
    echo -e "${BLUE}🔪 Принудительно завершаю остатки...${NC}"
    pkill -f "celery -A app.celery_app" || true
fi

# Удаляем старые PID файлы, если они есть (для очистки мусора)
rm -f logs/*.pid

# Финальная проверка всех процессов
echo -e "${BLUE}🔍 Финальная проверка...${NC}"
REMAINING=0

if pgrep -f "celery -A app.celery_app" > /dev/null; then
    echo -e "${RED}❌ Обнаружены оставшиеся Celery процессы:${NC}"
    pgrep -af "celery -A app.celery_app" | head -5
    REMAINING=1
fi

if pgrep -f "uvicorn main:app" > /dev/null; then
    echo -e "${RED}❌ Обнаружены оставшиеся Uvicorn процессы:${NC}"
    pgrep -af "uvicorn main:app"
    REMAINING=1
fi

if [ $REMAINING -eq 0 ]; then
    echo -e "${GREEN}🏁 Все сервисы остановлены успешно${NC}"
    exit 0
else
    echo -e "${RED}⚠️ Некоторые процессы остались запущенными${NC}"
    echo -e "${RED}Попробуйте запустить скрипт снова или завершите их вручную:${NC}"
    echo -e "${RED}  sudo pkill -9 -f 'celery -A app.celery_app'${NC}"
    echo -e "${RED}  sudo pkill -9 -f 'uvicorn main:app'${NC}"
    exit 1
fi

