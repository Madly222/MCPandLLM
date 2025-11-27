# tools/search_tool.py
import logging
import re
import json
from pathlib import Path
from typing import List, Dict, Optional, Any

from vector_store import vector_store
from tools.utils import BASE_FILES_DIR
from tools.file_tool import read_file
from tools.excel_tool import read_excel

logger = logging.getLogger(__name__)

# -----------------------
# Константы / настройки
# -----------------------
DEFAULT_KEYWORD_CONTEXT_CHARS = 300
MIN_PATTERN_LENGTH = 3
KEYWORD_STOP_WORDS = {
    'найди', 'поиск', 'покажи', 'открой', 'файл', 'файлы', 'документ',
    'таблица', 'таблицы', 'все', 'всех', 'данные', 'информация',
    'search', 'find', 'show', 'file', 'files', 'document', 'table',
    'сколько', 'проект', 'проекты', 'micb'  # micb можно убрать/оставить при необходимости
}


# -----------------------
# Хелперы
# -----------------------
def _to_text_from_table(raw: Any, max_chars: int = 20000) -> str:
    """
    Приводит результат read_excel к удобочитаемой текстовой форме.
    Поддерживает: str, list(dict), dict, pandas.DataFrame (если передали),
    и запасной вариант — str(raw).
    Для больших таблиц возвращает CSV-like preview (ограничение max_chars).
    """
    try:
        # Если уже строка
        if isinstance(raw, str):
            return raw[:max_chars]

        # Если это список словарей (типичная export-структура)
        if isinstance(raw, list):
            # Попробуем сериализовать в CSV-like: заголовки + строки
            if len(raw) == 0:
                return ""
            first = raw[0]
            if isinstance(first, dict):
                headers = list(first.keys())
                lines = [", ".join(headers)]
                for row in raw:
                    vals = [str(row.get(h, "")) for h in headers]
                    lines.append(", ".join(vals))
                    # контроль длины
                    if sum(len(l) for l in lines) > max_chars:
                        lines.append("...[table truncated]")
                        break
                return "\n".join(lines)

        # Если это dict (возможно mapping sheet->rows)
        if isinstance(raw, dict):
            # Попытка распечатать ключи и первые 5 строк каждого листа
            parts = []
            for k, v in raw.items():
                parts.append(f"=== Sheet: {k} ===")
                # v может быть list of dicts
                if isinstance(v, list) and v:
                    headers = list(v[0].keys()) if isinstance(v[0], dict) else []
                    if headers:
                        parts.append(", ".join(headers))
                    for i, row in enumerate(v):
                        if isinstance(row, dict):
                            parts.append(", ".join(str(row.get(h, "")) for h in headers))
                        else:
                            parts.append(str(row))
                        if len("\n".join(parts)) > max_chars:
                            parts.append("...[sheet truncated]")
                            break
                else:
                    parts.append(str(v)[:max_chars])
                if len("\n".join(parts)) > max_chars:
                    break
            return "\n".join(parts)[:max_chars]

        # Попытка распечатать pandas DataFrame (если пользователь передал)
        try:
            import pandas as pd
            if isinstance(raw, pd.DataFrame):
                # показать первые N строк в CSV-формате
                csv = raw.head(100).to_csv(index=False)
                return csv[:max_chars]
        except Exception:
            pass

        # По умолчанию — привести к строке
        return str(raw)[:max_chars]
    except Exception as e:
        logger.error(f"Ошибка при приведении таблицы к тексту: {e}")
        return ""


def _normalize_content(raw: Any, is_table: bool = False) -> str:
    """
    Универсальная нормализация контента: безопасно приводит любые типы к строке.
    Для таблиц использует _to_text_from_table для читаемого представления.
    """
    if raw is None:
        return ""

    if is_table:
        return _to_text_from_table(raw)

    # Для обычных файлов: если это строка — обрезаем и возвращаем
    if isinstance(raw, str):
        return raw

    # Если это bytes
    if isinstance(raw, (bytes, bytearray)):
        try:
            return raw.decode(errors="ignore")
        except Exception:
            return str(raw)

    # Если это list/dict/other — приведение в строку
    try:
        return str(raw)
    except Exception:
        try:
            return json.dumps(raw, ensure_ascii=False)
        except Exception:
            return repr(raw)


def is_error_response(content: str) -> bool:
    """Проверяет, является ли контент сообщением об ошибке"""
    if not content:
        return True
    return content.strip().startswith(("Ошибка", "Файл", "Error"))


def extract_filename_pattern(query: str) -> str:
    """
    Извлекает полезный паттерн из запроса:
    - находит слова длиной >= MIN_PATTERN_LENGTH
    - исключает стоп-слова
    - возвращает самое длинное слово или слово с наиб. встречаемостью
    """
    if not query:
        return ""

    tokens = re.findall(r'\b[A-Za-zА-Яа-я0-9_-]{%d,}\b' % MIN_PATTERN_LENGTH, query)
    tokens = [t for t in tokens if t.lower() not in KEYWORD_STOP_WORDS]

    if not tokens:
        return ""

    # вернуть самое длинное (как раньше), но учесть MICB-like tokens uppercase
    tokens.sort(key=lambda s: (-len(s), s))
    return tokens[0]


# -----------------------
# Поиск по ключевым словам внутри файлов (keyword)
# -----------------------
def keyword_search_in_files(query: str, top_n: int = 5, context_chars: int = DEFAULT_KEYWORD_CONTEXT_CHARS) -> List[Dict]:
    """
    Прямой поиск подстроки в файлах (текст + таблицы, таблицы приводятся к CSV-like preview).
    Возвращает список документов с snippet'ами.
    """
    hits: List[Dict] = []
    query_lower = (query or "").lower().strip()
    if not query_lower:
        return hits

    for filepath in BASE_FILES_DIR.iterdir():
        if not filepath.is_file():
            continue

        try:
            suffix = filepath.suffix.lower()
            is_table = False

            # ----------------
            # Чтение файла (без падений)
            # ----------------
            if suffix in {'.xlsx', '.xls', '.csv'}:
                raw = read_excel(filepath.name)
                is_table = True
                content = _normalize_content(raw, is_table=True)
            else:
                raw = read_file(filepath)
                content = _normalize_content(raw, is_table=False)

            if not isinstance(content, str):
                content = str(content)

            if is_error_response(content):
                continue

            content_lower = content.lower()

            # Поиск всех вхождений
            start = 0
            match_count = 0
            while True:
                pos = content_lower.find(query_lower, start)
                if pos == -1:
                    break

                context_start = max(0, pos - context_chars)
                context_end = min(len(content), pos + len(query) + context_chars)
                snippet = content[context_start:context_end].replace("\n", " ").strip()

                prefix = "..." if context_start > 0 else ""
                suffix_text = "..." if context_end < len(content) else ""

                hits.append({
                    "filename": filepath.name,
                    "filetype": suffix.lstrip('.'),
                    "content": f"{prefix}{snippet}{suffix_text}",
                    "is_table": is_table,
                    "chunk_index": match_count,
                    "total_chunks": -1,
                    "score": 1.0,
                    "match_type": "keyword"
                })

                match_count += 1
                if len(hits) >= top_n:
                    return hits

                start = pos + 1

        except Exception as e:
            logger.error(f"Ошибка keyword поиска в {filepath.name}: {e}")
            continue

    return hits


# -----------------------
# Поиск по имени файла (использует vector_store)
# -----------------------
def filename_search(query: str, user_id: str = "default", limit: int = 20) -> List[Dict]:
    """
    Поиск по имени файла через vector_store (metadata по имени).
    Если vector_store не подключён — возвращает [].
    """
    pattern = extract_filename_pattern(query)
    if not pattern:
        return []

    if not vector_store.is_connected():
        return []

    try:
        results = vector_store.search_by_filename(pattern, user_id, limit=limit) or []
        for r in results:
            r["match_type"] = "filename"
        return results
    except Exception as e:
        logger.error(f"Ошибка поиска по имени: {e}")
        return []


# -----------------------
# Семантический поиск (через vector_store)
# -----------------------
def semantic_search(query: str, user_id: str = "default", limit: int = 10) -> List[Dict]:
    """
    Семантический поиск через векторное хранилище.
    Ожидает, что vector_store.search_documents вернёт список dict с ключами filename, content, score и т.д.
    """
    if not vector_store.is_connected():
        logger.warning("Weaviate не подключен, семантический поиск недоступен")
        return []

    try:
        results = vector_store.search_documents(query, user_id, limit=limit) or []
        for r in results:
            r["match_type"] = "semantic"
        return results
    except Exception as e:
        logger.error(f"Ошибка семантического поиска: {e}")
        return []


# -----------------------
# Комбинированный умный поиск
# -----------------------
def smart_search(query: str, user_id: str = "default", limit: int = 10) -> List[Dict]:
    """
    1) Поиск по имени (filename)
    2) Семантический поиск
    3) Keyword fallback (локальный поиск по файлам)
    Dedup по имени файла. Возвращает максимум `limit` результатов.
    """
    results: List[Dict] = []
    seen = set()

    # Если weaviate не подключён — только keyword поиск
    if not vector_store.is_connected():
        logger.warning("Weaviate недоступен, используем только keyword поиск")
        return keyword_search_in_files(query, top_n=limit)

    # 1) Поиск по имени
    pattern = extract_filename_pattern(query)
    if pattern:
        logger.info(f"📁 Поиск по имени: '{pattern}'")
        name_hits = filename_search(query, user_id, limit=limit * 2)
        for doc in name_hits:
            key = doc.get("filename")
            if key and key not in seen:
                results.append(doc)
                seen.add(key)
        logger.info(f"   → Найдено по имени: {len(name_hits)}")

    # 2) Семантический поиск
    logger.info(f"🎯 Семантический поиск: '{query}'")
    semantic_results = semantic_search(query, user_id, limit=limit)
    added_semantic = 0
    for doc in semantic_results:
        key = doc.get("filename")
        if key and key not in seen:
            results.append(doc)
            seen.add(key)
            added_semantic += 1
    logger.info(f"   → Добавлено семантикой: {added_semantic}")

    # 3) Keyword fallback, если мало результатов
    if len(results) < 3:
        logger.info(f"🔎 Keyword fallback: '{query}'")
        keyword_results = keyword_search_in_files(query, top_n=limit)
        added_keyword = 0
        for doc in keyword_results:
            key = doc.get("filename")
            if key and key not in seen:
                results.append(doc)
                seen.add(key)
                added_keyword += 1
        logger.info(f"   → Добавлено keyword: {added_keyword}")

    # Сортировка по приоритету: filename > semantic > keyword и по score
    priority = {"filename": 0, "semantic": 1, "keyword": 2}
    results.sort(key=lambda x: (priority.get(x.get("match_type", "keyword"), 3), -float(x.get("score", 0))))

    logger.info(f"📊 Итого найдено: {len(results)} документов")
    return results[:limit]

def get_rag_context(query: str, user_id: str = "default", top_n: int = 10,
                    max_table_chars: int = 8000, max_doc_chars: int = 800) -> str:
    """
    Формирует контекст для RAG агента.
    Таблицы — показываются как CSV-preview (до max_table_chars).
    Документы — обрезаются до max_doc_chars.
    """
    results = smart_search(query, user_id, limit=top_n)
    if not results:
        return ""

    parts: List[str] = []
    parts.append("=== КОНТЕКСТ ИЗ ДОКУМЕНТОВ ===\n")

    for i, doc in enumerate(results, 1):
        doc_type = "ТАБЛИЦА" if doc.get("is_table") else "ДОКУМЕНТ"
        match_icons = {"filename": "📁", "semantic": "🎯", "keyword": "🔍"}
        match_icon = match_icons.get(doc.get("match_type", ""), "")

        chunk_info = ""
        total_chunks = doc.get("total_chunks", 1) or 1
        if total_chunks > 1:
            chunk_info = f" (чанк {doc.get('chunk_index', 0) + 1}/{total_chunks})"

        raw_content = doc.get("content", "")
        if doc.get("is_table"):
            content = raw_content[:max_table_chars]
            if len(raw_content) > max_table_chars:
                content += "\n...[таблица обрезана]"
        else:
            content = raw_content[:max_doc_chars]
            if len(raw_content) > max_doc_chars:
                content += "..."

        parts.append(f"--- [{doc_type}] {doc['filename']}{chunk_info} {match_icon} ---\n{content}\n")

    return "\n".join(parts)

def search_documents(query: str, user_id: str = "default", top_n: int = 5) -> str:
    """
    Возвращает человекочитаемый результат поиска (короткие превью).
    """
    results = smart_search(query, user_id, limit=top_n)
    if not results:
        return "❌ Ничего не найдено в документах."

    lines = ["🔍 **Результаты поиска:**\n"]
    for i, doc in enumerate(results, 1):
        content_preview = (doc.get("content") or "")[:400]
        if len(doc.get("content", "")) > 400:
            content_preview += "..."
        match_icons = {"filename": "📁", "semantic": "🎯", "keyword": "🔍"}
        match_icon = match_icons.get(doc.get("match_type", ""), "🔍")
        doc_icon = "📊" if doc.get("is_table") else "📄"

        chunk_info = ""
        total_chunks = doc.get("total_chunks", 1) or 1
        if total_chunks > 1:
            chunk_info = f" [часть {doc.get('chunk_index', 0) + 1}/{total_chunks}]"

        lines.append(f"{doc_icon} **{i}. {doc['filename']}**{chunk_info} {match_icon}\n{content_preview}\n")

    return "\n".join(lines)

def perform_search(query: str, user_id: str = "default", top_n: int = 5) -> str:
    return search_documents(query, user_id, top_n)


def get_raw_results(query: str, user_id: str = "default", top_n: int = 5) -> List[Dict]:
    return smart_search(query, user_id, limit=top_n)


def hybrid_search(query: str, user_id: str = "default", top_n: int = 5) -> List[Dict]:
    return smart_search(query, user_id, limit=top_n)