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

# Подключаем общие функции
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/common.sh"

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

# Настройка прокси: localhost/Redis без прокси, внешние API — через прокси.
# ВАЖНО: НЕ удаляем http_proxy/https_proxy, т.к. без прокси Python (httpx/SSL)
# не может подключиться к Google Gemini API из WSL2 — SSL handshake зависает.
export no_proxy="localhost,127.0.0.1,0.0.0.0,::1"
export NO_PROXY="localhost,127.0.0.1,0.0.0.0,::1"
if [ -n "$http_proxy" ] || [ -n "$HTTP_PROXY" ]; then
    echo -e "${GREEN}✅ HTTP прокси сохранен (no_proxy=localhost,127.0.0.1)${NC}"
    echo -e "   http_proxy=${http_proxy:-$HTTP_PROXY}"
else
    echo -e "${YELLOW}⚠️ HTTP прокси не обнаружен в окружении${NC}"
fi

# Показываем текущий режим RAG
ENABLE_RAG_SCHEDULE=${ENABLE_RAG_SCHEDULE:-false}
echo -e "${BLUE}📊 Режим RAG расписания: ${ENABLE_RAG_SCHEDULE}${NC}"
if [ "$ENABLE_RAG_SCHEDULE" = "true" ]; then
    echo -e "${YELLOW}💸 ВНИМАНИЕ: RAG задачи будут запускаться автоматически и тратить деньги на Google API!${NC}"
    echo -e "${YELLOW}   - Matcher: каждые ${RAG_MATCHER_INTERVAL_MINUTES:-360} минут${NC}"
    echo -e "${YELLOW}   - Deduplicator: ежедневно в ${RAG_DEDUP_HOUR:-3}:00${NC}"
else
    echo -e "${GREEN}💰 RAG задачи отключены. Деньги на Google API НЕ тратятся.${NC}"
    echo -e "${GREEN}   Для включения установите ENABLE_RAG_SCHEDULE=true в .env${NC}"
fi
echo ""

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

# --- CLEANUP SECTION ---
echo -e "${YELLOW}🧹 Cleaning up old processes and locks...${NC}"

# 1. Kill old celery processes aggressively
pkill -f "celery -A app.celery_app" || true

# 2. Remove old PID files
rm -f logs/*.pid

# 3. Remove local schedule file (we use RedBeat now, but just in case)
rm -f celerybeat-schedule.db

# 4. Wait a moment for ports to free up
sleep 2
echo -e "${GREEN}✅ Cleanup complete${NC}"
# -----------------------

# Устанавливаем зависимости, если requirements.txt изменился
REQUIREMENTS_HASH=$(md5sum requirements.txt | cut -d' ' -f1)
STORED_HASH=""
if [ -f ".dependencies_installed" ]; then
    STORED_HASH=$(cat .dependencies_installed)
fi

if [ "$REQUIREMENTS_HASH" != "$STORED_HASH" ]; then
    echo -e "${BLUE}📦 Устанавливаю зависимости...${NC}"
    pip install -r requirements.txt
    echo "$REQUIREMENTS_HASH" > .dependencies_installed
    echo -e "${GREEN}✅ Зависимости установлены${NC}"
fi

# 1. Воркер для парсинга (CPU-bound, высокая конкурентность)
start_service "celery-parser" \
    "celery -A app.celery_app worker --loglevel=INFO --queues=parser --concurrency=4 --hostname=parser@%h" \
    "logs/celery_parser.log"

# 2. Воркер для поискового индексатора (polling + embedding, низкая конкурентность)
start_service "celery-indexer" \
    "celery -A app.celery_app worker --loglevel=INFO --queues=indexer --concurrency=2 --hostname=indexer@%h" \
    "logs/celery_indexer.log"

# 3. Воркер для LLM / Gemini задач (rate-limited API, низкая конкурентность)
start_service "celery-llm" \
    "celery -A app.celery_app worker --loglevel=INFO --queues=llm --concurrency=2 --hostname=llm@%h" \
    "logs/celery_llm.log"

# 4. Воркер для общих/лёгких задач (cleanup и т.д.)
start_service "celery-default" \
    "celery -A app.celery_app worker --loglevel=INFO --queues=default --concurrency=1 --hostname=default@%h" \
    "logs/celery_default.log"

# Запускаем Celery Beat (планировщик)
start_service "celery-beat" \
    "celery -A app.celery_app beat --loglevel=INFO" \
    "logs/celery_beat.log"

# Запускаем Flower (мониторинг Celery)
start_service "flower" \
    "celery -A app.celery_app flower --port=5555" \
    "logs/flower.log"
echo -e "${GREEN}🌸 Flower доступен на http://localhost:5555${NC}"

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
echo -e "  - Celery Parser Worker:  logs/celery_parser.log"
echo -e "  - Celery Indexer Worker: logs/celery_indexer.log"
echo -e "  - Celery LLM Worker:     logs/celery_llm.log"
echo -e "  - Celery Default Worker: logs/celery_default.log"
echo -e "  - Celery Beat:           logs/celery_beat.log"
echo -e "  - FastAPI:               logs/fastapi.log"

# Запускаем FastAPI в фоне
nohup uvicorn main:app --host 0.0.0.0 --port 8000 --reload > logs/fastapi.log 2>&1 &
FASTAPI_PID=$!
echo -e "${GREEN}✅ FastAPI запущен (PID: $FASTAPI_PID)${NC}"

echo -e "${GREEN}🚀 Все сервисы успешно запущены!${NC}"
