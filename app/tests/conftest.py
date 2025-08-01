# app/tests/conftest.py
"""
Конфигурация для pytest.
Настройка общих фикстур и путей для всех тестов.
"""

import sys
from pathlib import Path

# Добавляем корень проекта в Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
