# Тестовые фикстуры

Эта директория содержит тестовые данные и golden-файлы для автотестов.

## Структура

```
fixtures/
├── excel/       # .xlsx-файлы для тестирования парсера
├── json/        # Golden JSON-файлы (эталонный вывод парсера)
└── gemini/      # Моки ответов Gemini API (JSON-записи)
```

---

## excel/ — тестовые Excel-файлы

Каждый файл покрывает конкретный сценарий. Имя файла отражает суть кейса.

### Правила именования

| Паттерн | Пример | Назначение |
|---------|--------|------------|
| `happy_path_*.xlsx` | `happy_path_single_lot.xlsx` | Корректный файл, «идеальный» кейс |
| `multi_lot_*.xlsx` | `multi_lot_3lots.xlsx` | Несколько лотов |
| `multi_contractor_*.xlsx` | `multi_contractor_4.xlsx` | 3+ подрядчиков |
| `dirty_*.xlsx` | `dirty_extra_empty_cols.xlsx` | Грязные данные |
| `edge_*.xlsx` | `edge_missing_header.xlsx` | Граничные случаи |
| `negative_*.xlsx` | `negative_no_lots.xlsx` | Негативные сценарии |

### Рекомендуемый минимальный набор

| Файл | Назначение |
|------|------------|
| `happy_path_single_lot.xlsx` | Один лот, один подрядчик, все поля заполнены |
| `happy_path_multi_lot.xlsx` | Два лота, один подрядчик |
| `multi_contractor_3.xlsx` | Три подрядчика в одном лоте |
| `dirty_extra_empty_cols.xlsx` | Лишние пустые колонки между подрядчиками |
| `dirty_merged_cells.xlsx` | Объединённые ячейки в шапке и позициях |
| `dirty_mixed_types.xlsx` | Числа вместо строк и наоборот |
| `edge_no_additional_info.xlsx` | Блок «Дополнительная информация» отсутствует |
| `edge_partial_executor.xlsx` | Неполный блок исполнителя |
| `negative_empty.xlsx` | Полностью пустой лист |
| `negative_wrong_structure.xlsx` | Файл, не похожий на тендер |

Статус создания этих файлов отслеживается в [`TESTING_CHECKLIST.md`](../../TESTING_CHECKLIST.md) (раздел «Тестовые данные и фикстуры»).

---

## json/ — golden JSON-файлы

Эталонные результаты парсинга, используемые в snapshot-тестах.

### Правила именования

Имя совпадает с именем `.xlsx`-файла-источника, расширение `.json`:

```
excel/happy_path_single_lot.xlsx  →  json/happy_path_single_lot.json
excel/multi_contractor_3.xlsx     →  json/multi_contractor_3.json
```

### Обновление golden-файлов

Если изменилась логика парсера и вывод валиден, обновите golden-файлы:

```bash
# Пересоздать конкретный golden-файл
python -m app.parse tests/fixtures/excel/happy_path_single_lot.xlsx \
  > tests/fixtures/json/happy_path_single_lot.json

# Обновить все golden-файлы (после проверки корректности вывода)
make update-golden
```

### Нормализация при сравнении

При сравнении с golden-файлом применяются следующие правила:
- Порядок ключей в словарях не имеет значения (используйте `assert result == expected`, где оба — `dict`)
- Порядок элементов в массивах `items` — значимый (позиции идут в том же порядке, что в Excel)
- Числовые значения сравниваются с допуском `1e-9` (`pytest.approx`)
- `null` и отсутствие ключа — разные вещи; golden-файл должен явно содержать `null` там, где он ожидается

---

## gemini/ — моки ответов Gemini API

JSON-файлы, имитирующие ответ Gemini API. Используются для изоляции тестов от сети.

### Формат файла

```json
{
  "request_hash": "sha256-хеш-промпта",
  "prompt_snippet": "первые 120 символов промпта",
  "response": {
    "candidates": [
      {
        "content": {
          "parts": [{ "text": "{ \"items\": [...] }" }]
        }
      }
    ]
  }
}
```

### Правила именования

```
gemini/response_<scenario>.json
```

Примеры:
- `gemini/response_simple_positions.json`
- `gemini/response_empty_input.json`
- `gemini/response_malformed_json.json` — тест устойчивости к невалидному JSON
- `gemini/response_timeout_error.json` — тест обработки ошибок API

### Стратегия мокирования Gemini

1. **Pytest fixture + monkeypatch** (рекомендуется для unit-тестов):

   ```python
   @pytest.fixture
   def mock_gemini(monkeypatch, fixture_path):
       response = json.loads((fixture_path / "gemini/response_simple_positions.json").read_text())
       monkeypatch.setattr("app.gemini_module.processor.GeminiClient.generate", lambda *a, **kw: response)
   ```

2. **VCR-like записи** (для интеграционных тестов): хранить реальные ответы API в `gemini/` и воспроизводить их через `pytest-recording` или собственный адаптер.

3. **Маркер `@pytest.mark.gemini`**: тесты с реальным Gemini вызовом помечаются этим маркером и пропускаются по умолчанию (`-m "not gemini"`).

---

## Общие правила

1. **Не коммитьте реальные тендерные данные** (персональные данные, коммерческая тайна). Используйте анонимизированные или синтетические данные.
2. **Размер файлов**: Excel-фикстуры должны быть минимальными (≤ 50 строк). Не добавляйте файлы > 1 MB без обоснования.
3. **Бинарные файлы** (`.xlsx`): коммитятся как есть. Для генерации синтетических файлов используйте скрипты в `scripts/generate_fixtures.py` (если появится).
4. **Актуальность**: после изменения парсера прогоните `make test-coverage` и убедитесь, что golden-тесты либо прошли, либо golden-файлы обновлены и изменение задокументировано в PR.
