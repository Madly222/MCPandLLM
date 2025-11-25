# tools/search_tool.py
import logging
import re
from pathlib import Path
from typing import List, Dict, Optional

from vector_store import vector_store
from tools.utils import BASE_FILES_DIR
from tools.file_tool import read_file
from tools.excel_tool import read_excel

logger = logging.getLogger(__name__)


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def is_error_response(content: str) -> bool:
    """Проверяет, является ли контент сообщением об ошибке"""
    if not content:
        return True
    return content.strip().startswith(("Ошибка", "Файл", "Error"))


def extract_filename_pattern(query: str) -> str:
    """
    Извлекает возможный паттерн имени файла из запроса.
    Возвращает самое длинное слово (минимум 3 символа).
    """
    # Ищем слова длиной 3+ символов
    patterns = re.findall(r'\b[A-Za-zА-Яа-я0-9_-]{3,}\b', query)

    # Исключаем стоп-слова
    stop_words = {
        'найди', 'поиск', 'покажи', 'открой', 'файл', 'файлы', 'документ',
        'таблица', 'таблицы', 'все', 'всех', 'данные', 'информация',
        'search', 'find', 'show', 'file', 'files', 'document', 'table'
    }

    patterns = [p for p in patterns if p.lower() not in stop_words]

    if patterns:
        return max(patterns, key=len)
    return ""


# ==================== МЕТОДЫ ПОИСКА ====================

def keyword_search_in_files(query: str, top_n: int = 5, context_chars: int = 300) -> List[Dict]:
    """
    Прямой поиск подстроки в файлах.
    Полезен для точного поиска: номера, коды, ИНН и т.д.
    """
    hits = []
    query_lower = query.lower()

    for filepath in BASE_FILES_DIR.iterdir():
        if not filepath.is_file():
            continue

        try:
            suffix = filepath.suffix.lower()

            # Читаем содержимое
            if suffix in ['.xlsx', '.xls']:
                content = read_excel(filepath.name)
                is_table = True
            else:
                content = read_file(filepath)
                is_table = False

            if is_error_response(content):
                continue

            content_lower = content.lower()

            # Ищем все вхождения
            start = 0
            match_count = 0

            while True:
                pos = content_lower.find(query_lower, start)
                if pos == -1:
                    break

                # Извлекаем контекст вокруг найденного
                context_start = max(0, pos - context_chars)
                context_end = min(len(content), pos + len(query) + context_chars)
                snippet = content[context_start:context_end].replace("\n", " ").strip()

                # Маркеры обрезки
                prefix = "..." if context_start > 0 else ""
                suffix_text = "..." if context_end < len(content) else ""

                hits.append({
                    "filename": filepath.name,
                    "filetype": filepath.suffix.lstrip('.'),
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


def filename_search(query: str, user_id: str = "default", limit: int = 20) -> List[Dict]:
    """
    Поиск по паттерну в имени файла.
    """
    pattern = extract_filename_pattern(query)
    if not pattern:
        return []

    if not vector_store.is_connected():
        return []

    try:
        results = vector_store.search_by_filename(pattern, user_id, limit=limit)
        for r in results:
            r["match_type"] = "filename"
        return results
    except Exception as e:
        logger.error(f"Ошибка поиска по имени: {e}")
        return []


def semantic_search(query: str, user_id: str = "default", limit: int = 10) -> List[Dict]:
    """
    Семантический поиск через Weaviate (по контенту).
    """
    if not vector_store.is_connected():
        logger.warning("Weaviate не подключен, семантический поиск недоступен")
        return []

    try:
        results = vector_store.search_documents(query, user_id, limit=limit)
        for r in results:
            r["match_type"] = "semantic"
        return results
    except Exception as e:
        logger.error(f"Ошибка семантического поиска: {e}")
        return []


# ==================== ОСНОВНАЯ ФУНКЦИЯ ПОИСКА ====================

def smart_search(query: str, user_id: str = "default", limit: int = 10) -> List[Dict]:
    """
    Умный комбинированный поиск:
    1. По имени файла (быстро, точно)
    2. Семантический поиск (по смыслу контента)
    3. Keyword fallback (точный поиск подстроки, если мало результатов)

    Дедупликация по имени файла.
    """
    results = []
    seen = set()

    # Если Weaviate недоступен — только keyword
    if not vector_store.is_connected():
        logger.warning("Weaviate недоступен, используем только keyword поиск")
        return keyword_search_in_files(query, top_n=limit)

    # ШАГ 1: Поиск по имени файла
    pattern = extract_filename_pattern(query)
    if pattern:
        logger.info(f"📁 Поиск по имени: '{pattern}'")
        for doc in filename_search(query, user_id, limit=20):
            key = doc["filename"]
            if key not in seen:
                results.append(doc)
                seen.add(key)
        logger.info(f"   → Найдено по имени: {len(results)}")

    # ШАГ 2: Семантический поиск
    logger.info(f"🎯 Семантический поиск: '{query}'")
    semantic_results = semantic_search(query, user_id, limit=limit)
    added_semantic = 0
    for doc in semantic_results:
        key = doc["filename"]
        if key not in seen:
            results.append(doc)
            seen.add(key)
            added_semantic += 1
    logger.info(f"   → Добавлено семантикой: {added_semantic}")

    # ШАГ 3: Keyword fallback (если мало результатов)
    if len(results) < 3:
        logger.info(f"🔎 Keyword fallback: '{query}'")
        keyword_results = keyword_search_in_files(query, top_n=limit)
        added_keyword = 0
        for doc in keyword_results:
            key = doc["filename"]
            if key not in seen:
                results.append(doc)
                seen.add(key)
                added_keyword += 1
        logger.info(f"   → Добавлено keyword: {added_keyword}")

    # Ранжирование: filename > semantic > keyword
    priority = {"filename": 0, "semantic": 1, "keyword": 2}
    results.sort(key=lambda x: (
        priority.get(x.get("match_type", "keyword"), 3),
        -x.get("score", 0)
    ))

    logger.info(f"📊 Итого найдено: {len(results)} документов")
    return results[:limit]


# ==================== ФУНКЦИИ ДЛЯ RAG И ВЫВОДА ====================

def get_rag_context(query: str, user_id: str = "default", top_n: int = 10,
                    max_table_chars: int = 8000, max_doc_chars: int = 800) -> str:
    """
    Формирует контекст для RAG/LLM агента.
    Таблицы — целиком (до max_table_chars).
    Документы — обрезаются (до max_doc_chars).
    """
    results = smart_search(query, user_id, limit=top_n)

    if not results:
        return ""

    context_parts = []
    context_parts.append("=== КОНТЕКСТ ИЗ ДОКУМЕНТОВ ===\n")

    for i, doc in enumerate(results, 1):
        doc_type = "ТАБЛИЦА" if doc.get("is_table") else "ДОКУМЕНТ"

        # Иконка типа поиска
        match_icons = {"filename": "📁", "semantic": "🎯", "keyword": "🔍"}
        match_icon = match_icons.get(doc.get("match_type", ""), "")

        # Информация о чанках
        chunk_info = ""
        if doc.get("total_chunks", 1) > 1:
            chunk_info = f" (чанк {doc.get('chunk_index', 0) + 1}/{doc.get('total_chunks', '?')})"

        # Контент: таблицы целиком, документы обрезаем
        if doc.get("is_table"):
            content = doc["content"][:max_table_chars]
            if len(doc["content"]) > max_table_chars:
                content += "\n...[таблица обрезана]"
        else:
            content = doc["content"][:max_doc_chars]
            if len(doc["content"]) > max_doc_chars:
                content += "..."

        context_parts.append(
            f"--- [{doc_type}] {doc['filename']}{chunk_info} {match_icon} ---\n"
            f"{content}\n"
        )

    return "\n".join(context_parts)


def search_documents(query: str, user_id: str = "default", top_n: int = 5) -> str:
    """
    Форматированный вывод для пользователя.
    """
    results = smart_search(query, user_id, limit=top_n)

    if not results:
        return "❌ Ничего не найдено в документах."

    lines = ["🔍 **Результаты поиска:**\n"]

    for i, doc in enumerate(results, 1):
        content_preview = doc["content"][:400]
        if len(doc["content"]) > 400:
            content_preview += "..."

        # Иконки
        match_icons = {"filename": "📁", "semantic": "🎯", "keyword": "🔍"}
        match_icon = match_icons.get(doc.get("match_type", ""), "🔍")
        doc_icon = "📊" if doc.get("is_table") else "📄"

        # Информация о чанках
        chunk_info = ""
        if doc.get("total_chunks", 1) > 1:
            chunk_info = f" [часть {doc.get('chunk_index', 0) + 1}/{doc.get('total_chunks', '?')}]"

        lines.append(
            f"{doc_icon} **{i}. {doc['filename']}**{chunk_info} {match_icon}\n"
            f"{content_preview}\n"
        )

    return "\n".join(lines)


# ==================== АЛИАСЫ ДЛЯ СОВМЕСТИМОСТИ ====================

def perform_search(query: str, user_id: str = "default", top_n: int = 5) -> str:
    """Alias для router.py"""
    return search_documents(query, user_id, top_n)


def get_raw_results(query: str, user_id: str = "default", top_n: int = 5) -> List[Dict]:
    """Возвращает сырые результаты (для программного использования)"""
    return smart_search(query, user_id, limit=top_n)


def hybrid_search(query: str, user_id: str = "default", top_n: int = 5) -> List[Dict]:
    """Alias для обратной совместимости"""
    return smart_search(query, user_id, limit=top_n)