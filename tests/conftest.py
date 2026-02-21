"""
Конфигурация pytest для корневой директории tests/.

Содержит общие фикстуры, доступные для всех тестов в tests/unit/,
tests/integration/ и tests/contract/.
"""

import pytest
from pathlib import Path


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Путь к директории с тестовыми фикстурами."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def excel_fixtures(fixtures_dir: Path) -> Path:
    """Путь к Excel-фикстурам (.xlsx файлы)."""
    return fixtures_dir / "excel"


@pytest.fixture(scope="session")
def json_fixtures(fixtures_dir: Path) -> Path:
    """Путь к golden JSON-файлам (эталонный вывод парсера)."""
    return fixtures_dir / "json"


@pytest.fixture(scope="session")
def gemini_fixtures(fixtures_dir: Path) -> Path:
    """Путь к мок-ответам Gemini API."""
    return fixtures_dir / "gemini"
