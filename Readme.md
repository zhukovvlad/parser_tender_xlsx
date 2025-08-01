# 🚀 Парсер и анализатор тендерной документации с Gemini AI

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![Gemini](https://img.shields.io/badge/AI-Gemini%202.5%20Pro-orange.svg)](https://ai.google.dev)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## 📖 Описание

Современный комплексный пайплайн на Python для интеллектуального анализа тендерной документации с использованием Google Gemini AI. Проект автоматизирует извлечение данных из Excel-файлов (XLSX), их смысловую обработку, категоризацию лотов и извлечение ключевых технических параметров.

## ✨ Ключевые особенности

- 🤖 **Gemini 2.5 Pro интеграция** - использование последней версии модели Google
- 🏗️ **Современная архитектура** - ООП подход с классом `TenderAnalyzer`
- 🔧 **Централизованная конфигурация** - все настройки в едином модуле
- 📝 **Профессиональное логирование** - детальные логи с уровнями и эмодзи
- 🛡️ **Расширенная обработка ошибок** - типизированные исключения и graceful recovery
- 💾 **Гибкое сохранение** - результаты в консоль и/или файл по выбору
- 📊 **Валидация данных** - проверка файлов и входных параметров
- 🎯 **CLI интерфейс** - удобные аргументы командной строки

## 🚀 Быстрый старт

### Установка

```bash
# Клонирование репозитория
git clone https://github.com/zhukovvlad/parser_tender_xlsx.git
cd parser_tender_xlsx

# Создание виртуального окружения
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# или .venv\Scripts\activate  # Windows

# Установка зависимостей
pip install -r requirements.txt
```

### Настройка

```bash
# Создайте .env файл на основе примера
cp .env.example .env

# Добавьте ваш API ключ Gemini
echo "GOOGLE_API_KEY=your_api_key_here" >> .env
```

### Использование

```bash
# Анализ файла по умолчанию
python test_tender.py

# Анализ конкретного файла
python test_tender.py document.md

# Анализ с сохранением в файл
python test_tender.py --output results.json

# Подробный режим с детальными логами
python test_tender.py --verbose

# Все опции вместе
python test_tender.py mydoc.md --output analysis.json --verbose
```

## 📁 Структура проекта

```
parser_tender_xlsx/
├── 📄 test_tender.py              # 🎯 Основной скрипт (symlink на refactored)
├── 📄 _test_tender_refactored.py  # ✨ Новая версия с современной архитектурой  
├── 📄 _test_tender.py             # ⚠️  Устаревшая версия (deprecated)
├── 📄 main.py                     # 🔧 Парсер XLSX файлов
├── 📄 requirements.txt            # 📦 Зависимости Python
├── 📄 pyproject.toml             # ⚙️  Конфигурация проекта
│
├── 📂 app/                       # 🏗️ Основная логика приложения
│   ├── 📂 gemini_module/         # 🤖 Модуль работы с Gemini AI
│   │   ├── config.py             # ⚙️  Централизованная конфигурация
│   │   ├── constants.py          # 📊 Константы и шаблоны категорий
│   │   └── processor.py          # 🔄 Класс TenderProcessor
│   │
│   ├── 📂 helpers/               # 🛠️ Вспомогательные функции
│   ├── 📂 markdown_utils/        # 📝 Утилиты для Markdown
│   ├── 📂 json_to_server/        # 🌐 Отправка данных на сервер
│   └── 📂 tests/                 # 🧪 Тесты
│
├── 📂 tenders_xlsx/              # 📊 Исходные XLSX файлы
├── 📂 tenders_json/              # 📄 Обработанные JSON файлы  
├── 📂 logs/                      # 📊 Файлы логов
└── 📂 temp_uploads/              # 🗂️ Временные файлы
```

## 🔄 Процесс обработки данных

### 1. 📊 Парсинг XLSX файлов (`main.py`)

1. **Парсинг XLSX** - извлечение данных из исходного файла
2. **Постобработка** - нормализация структуры, очистка данных  
3. **Регистрация в БД** - отправка данных на Go-сервер для получения уникальных ID
4. **Генерация артефактов** - создание JSON и Markdown файлов
5. **Архивация** - перемещение всех файлов в соответствующие директории

### 2. 🤖 ИИ-анализ документов (`test_tender.py`)

1. **Загрузка файла** - валидация и отправка на Gemini API
2. **Классификация** - автоматическое определение категории лота
3. **Извлечение параметров** - структурированное извлечение технических данных
4. **Вывод результатов** - JSON с метаданными и анализом
5. **Очистка ресурсов** - автоматическое удаление временных файлов

## 🏗️ Архитектура

### Класс TenderAnalyzer

```python
class TenderAnalyzer:
    def __init__(self, api_key: str)          # Инициализация с API ключом
    def analyze_document(self, file: Path)     # Полный анализ документа
    def _classify_document(self) -> str        # Классификация по категориям
    def _extract_data(self, category: str)     # Извлечение данных
    def _cleanup(self)                         # Очистка ресурсов
```

### Конфигурация

```python
# app/gemini_module/config.py
MODEL_CONFIG = {
    "default_model": "models/gemini-2.5-pro",
    "temperature": 0.1,
    "max_tokens": 8192,
}
```

## 📊 Примеры использования

### Базовый анализ

```bash
python test_tender.py

# Вывод:
# 🚀 Запускаем интеллектуальный анализ документа: 42_42_positions.md  
# ⏳ Определяю категорию документа...
# ✅ Документ классифицирован как: 'Нулевой цикл'
# 🎉 Анализ завершён успешно
```

### Результат анализа

```json
{
  "earthworks_scope": [90947.2, 738.3, 5000],
  "retaining_structures": "Стена в грунте", 
  "piling_required": "да",
  "determined_tender_type": "Нулевой цикл",
  "source_file": "document.md",
  "analysis_success": true
}
```

### Программное использование

```python
from app.gemini_module import TenderAnalyzer
from pathlib import Path
import os

analyzer = TenderAnalyzer(os.getenv("GOOGLE_API_KEY"))
results = analyzer.analyze_document(Path("document.md"))

if results["analysis_success"]:
    print(f"Категория: {results['determined_tender_type']}")
```

## 🔍 Поддерживаемые категории

| Категория | Описание | Параметры |
|-----------|----------|-----------|
| **Нулевой цикл** | Земляные работы, фундаменты | Объемы работ, характеристики свай |
| **Инженерные сети** | Коммуникации, трубопроводы | Диаметры, материалы, протяженность |
| **Строительство зданий** | Возведение конструкций | Материалы, объемы работ |
| **Благоустройство** | Дорожные работы, озеленение | Площади, материалы покрытий |
| **Прочее** | Fallback категория | Общие параметры |

## 🔧 Конфигурация

### Переменные окружения (.env)

```bash
# Основная конфигурация
GOOGLE_API_KEY=your_gemini_api_key_here
LOG_LEVEL=INFO                    # DEBUG, INFO, WARNING, ERROR

# Конфигурация сервера (для main.py)
BASE_URL=http://localhost:8080
TIMEOUT=30
ENABLE_FALLBACK=true
```

## 📋 Требования

- **Python 3.12+** (рекомендуется)
- **Google Gemini API ключ** - для ИИ-анализа документов  
- **Виртуальное окружение** - для изоляции зависимостей

### Ключевые зависимости

```txt  
google-genai>=1.28.0     # Gemini API клиент
openpyxl>=3.1.5          # Работа с Excel файлами
python-dotenv>=1.1.0     # Переменные окружения
requests>=2.32.3         # HTTP запросы
```

## 🚨 Устранение неполадок

### API ключ не найден
```bash
❌ API ключ не найден
# Решение:
echo "GOOGLE_API_KEY=your_key" >> .env
```

### Файл слишком большой
```bash  
❌ Файл слишком большой: 75.5MB (максимум: 50MB)
# Решение: разбейте файл на части
```

## 📄 Лицензия

Этот проект распространяется под лицензией MIT.

---

<div align="center">

**Создано с ❤️ для автоматизации анализа тендерной документации**

[🚀 Начать использование](#-быстрый-старт) • [📖 Документация](#-структура-проекта) • [🔧 Конфигурация](#-конфигурация)

</div>
