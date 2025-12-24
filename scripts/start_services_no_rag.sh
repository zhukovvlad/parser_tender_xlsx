#!/bin/bash

# Скрипт запуска сервисов БЕЗ RAG воркеров (для экономии денег на Google API)
# Запускает только Gemini воркер для парсинга тендеров

# Определяем директорию проекта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT" || { echo "Ошибка: не удалось перейти в директорию $PROJECT_ROOT"; exit 1; }

# Цвета для вывода
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}🚀 Запуск сервисов (БЕЗ RAG)${NC}"
echo -e "${GREEN}================================${NC}"
echo ""

# Проверяем, что виртуальное окружение активно
if [[ -z "$VIRTUAL_ENV" ]]; then
    echo -e "${YELLOW}⚠️ Виртуальное окружение не активно${NC}"
    echo -e "${BLUE}Активирую .venv...${NC}"
    source .venv/bin/activate || { echo -e "${RED}❌ Не удалось активировать .venv${NC}"; exit 1; }
fi

# Проверяем Redis
echo -e "${BLUE}🔍 Проверяю Redis...${NC}"
if redis-cli ping > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Redis доступен${NC}"
else
    echo -e "${RED}❌ Redis недоступен. Запустите Redis сервер${NC}"
    exit 1
fi

# Создаем директорию для логов если её нет
mkdir -p logs

# Функция для запуска сервиса в фоне
start_service() {
    local name=$1
    local command=$2
    local logfile=$3
    
    echo -e "${BLUE}🚀 Запускаю $name...${NC}"
    nohup $command > $logfile 2>&1 &
    local pid=$!
    echo -e "${GREEN}✅ $name запущен (PID: $pid)${NC}"
}

# 1. Запускаем ТОЛЬКО AI воркер для Gemini (парсинг тендеров)
# Слушает ТОЛЬКО очередь ai_queue, работает в 1 поток
start_service "celery-ai" \
    "celery -A app.celery_app worker --loglevel=INFO --queues=ai_queue --concurrency=1 --hostname=ai@%h" \
    "logs/celery_ai.log"

# 2. НЕ запускаем Default воркер (он запускает RAG задачи по расписанию)
echo -e "${YELLOW}⚠️ Default воркер не запущен (RAG задачи отключены)${NC}"

# 3. НЕ запускаем Celery Beat (планировщик RAG задач)
echo -e "${YELLOW}⚠️ Celery Beat не запущен (расписание отключено)${NC}"

# 4. Запускаем Flower для мониторинга (опционально)
read -p "$(echo -e ${BLUE}Запустить Flower для мониторинга? [y/N]: ${NC})" -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
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
    echo -e "${BLUE}Активные воркеры:${NC}"
    celery -A app.celery_app inspect active
else
    echo -e "${YELLOW}⚠️ Воркеры еще запускаются...${NC}"
fi

# Запускаем FastAPI приложение (если нужно)
read -p "$(echo -e ${BLUE}Запустить FastAPI сервер? [y/N]: ${NC})" -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${BLUE}🌐 Запускаю FastAPI приложение...${NC}"
    start_service "fastapi" \
        "uvicorn main:app --host 0.0.0.0 --port 8000 --reload" \
        "logs/fastapi.log"
    echo -e "${GREEN}✅ FastAPI доступен на http://localhost:8000${NC}"
fi

echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}✅ Запуск завершен${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo -e "${GREEN}📝 Логи сервисов:${NC}"
echo -e "  - Celery AI Worker: logs/celery_ai.log"
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "  - FastAPI: logs/fastapi.log"
fi
echo ""
echo -e "${BLUE}📊 Мониторинг:${NC}"
echo -e "  - Проверить воркеры: celery -A app.celery_app inspect active"
echo -e "  - Просмотр логов: tail -f logs/celery_ai.log"
echo -e "  - Остановить: ./scripts/stop_services.sh"
echo ""
echo -e "${YELLOW}⚠️ RAG воркеры отключены - Google API не используется${NC}"
echo -e "${YELLOW}   Для полного функционала используйте ./scripts/start_services.sh${NC}"
