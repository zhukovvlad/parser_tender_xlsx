import re
from typing import Any, Optional, List


# --- Новый блок импортов и инициализации для spaCy ---
SPACY_AVAILABLE = False
NLP_SPACY = None
try:
    import spacy
    # Загружаем модель spaCy. 'ru_core_news_sm' - маленькая модель.
    # Для лучшего качества можно использовать 'ru_core_news_md' или 'ru_core_news_lg',
    # но они больше по размеру и медленнее.
    NLP_SPACY = spacy.load("ru_core_news_sm")
    SPACY_AVAILABLE = True
    print("DEBUG: Модель spaCy 'ru_core_news_sm' успешно загружена.")
except ImportError:
    print("ПРЕДУПРЕЖДЕНИЕ: Библиотека spaCy не найдена. "
          "Пожалуйста, установите ее: pip install spacy. "
          "Лемматизация spaCy будет пропущена.")
except OSError:
    # Эта ошибка возникает, если spaCy установлен, но модель не загружена.
    print("ПРЕДУПРЕЖДЕНИЕ: Модель spaCy 'ru_core_news_sm' не найдена. "
          "Пожалуйста, скачайте ее командой: python -m spacy download ru_core_news_sm. "
          "Лемматизация spaCy будет пропущена.")
except Exception as e:
    print(f"ПРЕДУПРЕЖДЕНИЕ: Непредвиденная ошибка при инициализации spaCy: {e}. "
          "Лемматизация spaCy будет пропущена.")
# --- Конец блока spaCy ---

def sanitize_text(text: Any) -> Any:
    """
    Выполняет базовую очистку (санитизацию) входных данных, если они являются строкой.

    Если входные данные `text` являются строкой, функция выполняет следующие действия:
    1.  Заменяет все символы перевода строки (`\\n`) на пробелы.
    2.  Удаляет все символы возврата каретки (`\\r`).
    3.  Удаляет начальные и конечные пробельные символы из результирующей строки.
    
    Примечание: Эта функция НЕ удаляет кавычки из строки.

    Если входные данные не являются строкой (например, число, None, список),
    функция возвращает их без изменений.

    Args:
        text (Any): Входные данные для санитизации. Ожидается, что это может
            быть строка или любой другой тип данных.

    Returns:
        Any: Очищенная строка (обработаны `\\n`, `\\r`, удалены крайние пробелы),
            если на вход была подана строка. Двойные кавычки остаются без изменений.
            В противном случае — исходные данные без изменений.

    Примеры:
        sanitize_text("  Пример\\nтекста\\r\\n с пробелами  ") == "Пример текста с пробелами"
        sanitize_text("Текст с \\"кавычками\\"") == "Текст с \\"кавычками\\""
        sanitize_text(None) == None
        sanitize_text(123) == 123
    """
    # Проверяем, являются ли входные данные строкой
    if isinstance(text, str):
        # Заменяем символы новой строки на пробел, удаляем возврат каретки,
        # затем удаляем пробелы по краям. Кавычки не трогаем.
        sanitized_string = text.replace('\n', ' ')
        sanitized_string = sanitized_string.replace('\r', '').strip()
        return sanitized_string
    
    # Если это не строка, возвращаем исходные данные без изменений
    return text

def sanitize_object_and_address_text(text: Any) -> Any:
    """
    Выполняет специфическую очистку для текстовых данных, представляющих
    названия объектов или адреса.

    Если входные данные `text` являются строкой, функция выполняет:
    1.  Удаление всех символов точки (`.`).
    2.  Приведение всей строки к нижнему регистру.
    3.  Удаление начальных и конечных пробельных символов.
    
    Кавычки в этой функции также не удаляются (так как она может вызывать `sanitize_text`).

    Если входные данные не являются строкой, они передаются в `sanitize_text`,
    которая вернет их без изменений (если это не строка).

    Args:
        text (Any): Входные данные для очистки.

    Returns:
        Any: Очищенная и нормализованная строка (без точек, в нижнем регистре,
            без крайних пробелов), если на вход была подана строка.
            Кавычки остаются. В противном случае — исходные данные без изменений.

    Примеры:
        sanitize_object_and_address_text("Ул. Ленина, д. 5, КОРП. 1А.") == "ул ленина д 5 корп 1а"
        sanitize_object_and_address_text('  Объект "Капитель" с Большими Буквами.  ') == 'объект "капитель" с большими буквами'
        sanitize_object_and_address_text(None) == None
        sanitize_object_and_address_text(123) == 123
    """
    if isinstance(text, str):
        # Удаляем все точки, приводим к нижнему регистру, удаляем пробелы по краям
        sanitized_text_val = text.replace('.', '').lower().strip()
        return sanitized_text_val
    # Для не-строк, sanitize_text(text) просто вернет text, так как sanitize_text
    # не меняет не-строковые типы и в текущей версии не трогает кавычки.
    return sanitize_text(text)

def normalize_job_title_with_lemmatization(text: Optional[str]) -> Optional[str]:
    """
    Выполняет продвинутую нормализацию текста (например, для job_title),
    включая очистку от Markdown, удаление пунктуации, приведение
    к нижнему регистру и лемматизацию с использованием библиотеки spaCy.

    Шаги обработки:
    1. Приведение к строке и нижнему регистру.
    2. Удаление базовой Markdown-разметки (жирный, курсив, "---").
    3. Замена большинства знаков препинания на пробелы (дефисы внутри слов сохраняются).
    4. Консолидация пробелов.
    5. Если spaCy доступна и модель загружена:
        a. Обработка текста с помощью spaCy.
        b. Извлечение лемм (`token.lemma_`) для всех токенов, не являющихся
           знаками препинания или пробельными символами.
        c. Объединение лемм в строку.
    6. Финальная нормализация множественных пробелов и удаление крайних пробелов.

    Args:
        text (Optional[str]): Исходный текст для нормализации.

    Returns:
        Optional[str]: Нормализованный и (если возможно) лемматизированный текст
                       или None, если исходный текст был None или результат пуст.
    """
    # print(f"\n>>> JOB_TITLE_NORM (spaCy): Вход: '{text}'") # Отладка

    if text is None:
        # print(">>> JOB_TITLE_NORM (spaCy): Исходный текст None, возврат None.")
        return None
    
    # Базовая очистка текста перед передачей в spaCy или если spaCy недоступен
    cleaned_text = str(text).lower()
    cleaned_text = re.sub(r'(\*\*|__)(.+?)(\1)', r'\2', cleaned_text)
    cleaned_text = re.sub(r'(?<![\wА-Яа-я])(\*|_)(.+?)(\1)(?![\wА-Яа-я])', r'\2', cleaned_text)
    cleaned_text = cleaned_text.replace("---", " ")
    cleaned_text = re.sub(r'[^\w\s-]', ' ', cleaned_text) 
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
    # print(f">>> JOB_TITLE_NORM (spaCy): Текст после начальной очистки: '{cleaned_text}'")

    if not cleaned_text:
        # print(">>> JOB_TITLE_NORM (spaCy): Текст пуст после начальной очистки, возврат None.")
        return None

    processed_text_for_join = cleaned_text # Значение по умолчанию, если лемматизация не сработает

    if SPACY_AVAILABLE and NLP_SPACY:
        try:
            doc = NLP_SPACY(cleaned_text) # Обрабатываем уже частично очищенный текст
            
            lemmatized_words: List[str] = []
            # print(f">>> JOB_TITLE_NORM (spaCy): Токены spaCy для '{cleaned_text}':")
            for token_idx, token in enumerate(doc):
                # print(f"  Токен {token_idx}: text='{token.text}', lemma='{token.lemma_}', pos='{token.pos_}', is_punct={token.is_punct}, is_space={token.is_space}")
                if not token.is_punct and not token.is_space and token.lemma_: # Проверяем, что лемма не пустая
                    lemmatized_words.append(token.lemma_) # spaCy леммы обычно уже в нижнем регистре
            
            if not lemmatized_words:
                # print(f">>> JOB_TITLE_NORM (spaCy): Список лемматизированных слов пуст для: '{cleaned_text}'")
                pass # processed_text_for_join останется cleaned_text
            else:
                processed_text_for_join = " ".join(lemmatized_words)
            
            # print(f">>> JOB_TITLE_NORM (spaCy): Текст после лемматизации и join: '{processed_text_for_join}'")

        except Exception as e:
            print(f"ПРЕДУПРЕЖДЕНИЕ: Ошибка во время лемматизации с spaCy для текста '{cleaned_text[:50]}...': {e}")
            print("ПРЕДУПРЕЖДЕНИЕ: Лемматизация для этого текста будет пропущена, используется текст после базовой очистки.")
            # processed_text_for_join уже равен cleaned_text
    else:
        # Сообщение об отсутствии spaCy уже было выведено при инициализации
        # print(">>> JOB_TITLE_NORM (spaCy): spaCy недоступен. Используется текст после базовой очистки.")
        pass # processed_text_for_join уже равен cleaned_text
    
    final_text = re.sub(r'\s+', ' ', processed_text_for_join).strip()
    # print(f">>> JOB_TITLE_NORM (spaCy): Финальный текст: '{final_text}'")
    
    result = final_text if final_text else None
    # print(f">>> JOB_TITLE_NORM (spaCy): Возврат: '{result}'")
    return result