#!/bin/bash
# scripts/start_services.sh

#
# Скрипт для запуска всех сервисов проекта:
# - Redis (если не запущен)
# - Celery Worker (фоновая обработка)
# - Celery Beat (планировщик задач)
# - FastAPI приложение
#

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Starting Tender Parser Services${NC}"

# Проверяем, что мы в корне проекта
if [ ! -f "main.py" ]; then
    echo -e "${RED}❌ Ошибка: Запустите скрипт из корня проекта${NC}"
    exit 1
fi

# Активируем виртуальное окружение
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo -e "${GREEN}✅ Виртуальное окружение активировано${NC}"
else
    echo -e "${RED}❌ Не найдено виртуальное окружение .venv${NC}"
    exit 1
fi

# Загружаем переменные окружения
if [ -f ".env" ]; then
    source .env
    echo -e "${GREEN}✅ Переменные окружения загружены${NC}"
else
    echo -e "${YELLOW}⚠️ Файл .env не найден${NC}"
fi

# Проверяем Redis
echo -e "${BLUE}🔍 Проверяю Redis...${NC}"
if redis-cli ping > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Redis запущен${NC}"
else
    echo -e "${YELLOW}⚠️ Redis не запущен. Запускаю...${NC}"
    redis-server --daemonize yes
    sleep 2
    if redis-cli ping > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Redis запущен успешно${NC}"
    else
        echo -e "${RED}❌ Не удалось запустить Redis${NC}"
        exit 1
    fi
fi

# Создаем необходимые директории
mkdir -p logs temp_uploads

# Устанавливаем зависимости, если нужно
if [ ! -f ".dependencies_installed" ]; then
    echo -e "${BLUE}📦 Устанавливаю зависимости...${NC}"
    pip install -r requirements.txt
    touch .dependencies_installed
    echo -e "${GREEN}✅ Зависимости установлены${NC}"
fi

# Функция для запуска сервиса в фоне
start_service() {
    local name=$1
    local command=$2
    local logfile=$3
    
    echo -e "${BLUE}🚀 Запускаю $name...${NC}"
    nohup $command > $logfile 2>&1 &
    local pid=$!
    echo $pid > "logs/${name}.pid"
    echo -e "${GREEN}✅ $name запущен (PID: $pid)${NC}"
}

# Запускаем Celery Worker
start_service "celery-worker" \
    "celery -A app.celery_app worker --loglevel=INFO --queues=default" \
    "logs/celery_worker.log"

# Запускаем Celery Beat (планировщик)
start_service "celery-beat" \
    "celery -A app.celery_app beat --loglevel=INFO" \
    "logs/celery_beat.log"

# Запускаем Flower (мониторинг Celery) - опционально
if command -v flower &> /dev/null; then
    start_service "flower" \
        "celery -A app.celery_app flower --port=5555" \
        "logs/flower.log"
    echo -e "${GREEN}🌸 Flower доступен на http://localhost:5555${NC}"
fi

# Ждем немного, чтобы сервисы запустились
sleep 3

# Проверяем статус воркеров
echo -e "${BLUE}🔍 Проверяю статус воркеров...${NC}"
if celery -A app.celery_app inspect ping > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Celery воркеры активны${NC}"
else
    echo -e "${YELLOW}⚠️ Воркеры еще запускаются...${NC}"
fi

# Запускаем FastAPI приложение
echo -e "${BLUE}🌐 Запускаю FastAPI приложение...${NC}"
echo -e "${GREEN}📝 Логи сервисов:${NC}"
echo -e "  - Celery Worker: logs/celery_worker.log"
echo -e "  - Celery Beat: logs/celery_beat.log"
echo -e "  - FastAPI: будет выводиться в консоль"

# Запускаем FastAPI (не в фоне, чтобы видеть логи)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
