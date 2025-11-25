import logging
from pathlib import Path
from typing import List, Dict, Optional

from vector_store import vector_store
from tools.utils import BASE_FILES_DIR
from tools.file_tool import read_file
from tools.excel_tool import read_excel

logger = logging.getLogger(__name__)


def is_error_response(content: str) -> bool:
    """Проверяет, является ли контент сообщением об ошибке"""
    if not content:
        return True
    return content.strip().startswith(("Ошибка", "Файл", "Error"))


def keyword_search_in_files(query: str, top_n: int = 5, context_chars: int = 300) -> List[Dict]:
    """
    Прямой поиск подстроки в файлах (fallback).
    Возвращает все найденные совпадения с контекстом.
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

                # Добавляем маркеры начала/конца если обрезано
                prefix = "..." if context_start > 0 else ""
                suffix_text = "..." if context_end < len(content) else ""

                hits.append({
                    "filename": filepath.name,
                    "filetype": filepath.suffix.lstrip('.'),
                    "content": f"{prefix}{snippet}{suffix_text}",
                    "is_table": is_table,
                    "chunk_index": match_count,
                    "total_chunks": -1,  # Неизвестно для keyword поиска
                    "score": 1.0,
                    "match_type": "keyword"
                })

                match_count += 1

                if len(hits) >= top_n:
                    return hits

                start = pos + 1

        except Exception as e:
            logger.error(f"Ошибка поиска в {filepath.name}: {e}")
            continue

    return hits


def semantic_search(query: str, user_id: str = "default", limit: int = 10) -> List[Dict]:
    """Семантический поиск через Weaviate"""
    if not vector_store.is_connected():
        logger.warning("Weaviate не подключен, семантический поиск недоступен")
        return []

    try:
        results = vector_store.search_documents(query, user_id, limit=limit)

        # Добавляем тип поиска
        for r in results:
            r["match_type"] = "semantic"

        return results
    except Exception as e:
        logger.error(f"Ошибка семантического поиска: {e}")
        return []


def hybrid_search(query: str, user_id: str = "default", top_n: int = 5) -> List[Dict]:
    """
    Гибридный поиск: semantic + keyword.
    Дедупликация по контенту, а не по filename (для корректной работы с чанками).
    """

    # 1. Семантический поиск
    semantic_results = semantic_search(query, user_id, limit=top_n * 2)

    # 2. Если семантика дала мало результатов — добавляем keyword
    if len(semantic_results) < 3:
        logger.info("Дополняем keyword поиском...")
        keyword_results = keyword_search_in_files(query, top_n=top_n)

        # Дедупликация по контенту (первые 100 символов), не по filename
        seen_content = {r["content"][:100] for r in semantic_results}

        for kr in keyword_results:
            content_key = kr["content"][:100]
            if content_key not in seen_content:
                semantic_results.append(kr)
                seen_content.add(content_key)

    # 3. Ранжируем: semantic выше, затем по score
    semantic_results.sort(key=lambda x: (
        0 if x["match_type"] == "semantic" else 1,
        -x.get("score", 0)
    ))

    return semantic_results[:top_n]


def get_rag_context(query: str, user_id: str = "default", top_n: int = 5,
                    max_table_chars: int = 10000, max_doc_chars: int = 800) -> str:
    """
    Формирует контекст для RAG/LLM агента.
    Таблицы передаются ЦЕЛИКОМ (до max_table_chars).
    Обычные документы обрезаются до max_doc_chars.
    """
    results = hybrid_search(query, user_id, top_n)

    if not results:
        return ""

    context_parts = []
    context_parts.append("=== КОНТЕКСТ ИЗ ДОКУМЕНТОВ ===\n")

    for i, doc in enumerate(results, 1):
        doc_type = "ТАБЛИЦА" if doc.get("is_table") else "ДОКУМЕНТ"
        chunk_info = ""

        if doc.get("total_chunks", 1) > 1:
            chunk_info = f" (чанк {doc.get('chunk_index', 0) + 1}/{doc.get('total_chunks', '?')})"

        # ✅ Таблицы — полностью, документы — обрезаем
        if doc.get("is_table"):
            content = doc["content"][:max_table_chars]
            if len(doc["content"]) > max_table_chars:
                content += "\n...[таблица обрезана]"
        else:
            content = doc["content"][:max_doc_chars]
            if len(doc["content"]) > max_doc_chars:
                content += "..."

        context_parts.append(
            f"--- [{doc_type}] {doc['filename']}{chunk_info} ---\n"
            f"{content}\n"
        )

    return "\n".join(context_parts)


def search_documents(query: str, user_id: str = "default", top_n: int = 5) -> str:
    """
    Главная функция поиска — форматированный вывод для пользователя.
    Для RAG агента используй get_rag_context().
    """
    results = hybrid_search(query, user_id, top_n)

    if not results:
        return "❌ Ничего не найдено в документах."

    lines = ["🔍 **Результаты поиска:**\n"]

    for i, doc in enumerate(results, 1):
        content_preview = doc["content"][:400]
        if len(doc["content"]) > 400:
            content_preview += "..."

        # Иконки и метаданные
        if doc.get("match_type") == "semantic":
            match_icon = "🎯"
        else:
            match_icon = "🔍"

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


def perform_search(query: str, user_id: str = "default", top_n: int = 5) -> str:
    """Alias для совместимости с router.py"""
    return search_documents(query, user_id, top_n)


def get_raw_results(query: str, user_id: str = "default", top_n: int = 5) -> List[Dict]:
    """
    Возвращает сырые результаты поиска (для программного использования).
    """
    return hybrid_search(query, user_id, top_n)