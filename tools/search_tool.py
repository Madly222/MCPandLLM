# tools/search_tool.py
from vector_store.wv_store import WeaviateStore
from tools.chunking_tool import chunk_text, read_file_content, BASE_FILES_DIR
from typing import List, Dict, Optional
import logging
import os

logger = logging.getLogger(__name__)

store = WeaviateStore()


def brute_force_search_files(query: str, top_n: int = 5) -> List[Dict]:
    """
    Простой поиск подстроки query по всем файлам в BASE_FILES_DIR.
    Возвращает список чанков с полями: filename, chunk_index, content, score.
    """
    hits = []
    q = query.lower()

    for f in BASE_FILES_DIR.iterdir():
        if not f.is_file():
            continue

        content = read_file_content(f)
        if not content or content.startswith("Ошибка"):
            continue

        if q in content.lower():
            start = content.lower().index(q)
            begin = max(0, start - 120)
            end = min(len(content), start + len(q) + 120)
            snippet = content[begin:end].replace("\n", " ").strip()
            hits.append({
                "filename": f.name,
                "chunk_index": 0,
                "content": snippet,
                "score": 1.0
            })
            if len(hits) >= top_n:
                break

    return hits


def search_documents(query: str, user_id: Optional[str] = None, top_n: int = 5) -> List[Dict]:
    """
    Семантический поиск с fallback на прямой поиск по файлам.
    Возвращает список чанков с полями: filename, chunk_index, content, score.
    """
    if not store.is_connected():
        logger.warning("Weaviate не подключен. Используем прямой поиск по файлам.")
        return brute_force_search_files(query, top_n=top_n)

    logger.info(f"Поиск в Weaviate: '{query}' для user_id={user_id}")
    results = store.search_documents(query, user_id=user_id, limit=top_n)

    # fallback на прямой поиск, если семантика пустая
    if not results:
        logger.info("Weaviate вернул 0 результатов. Пробуем прямой поиск по файлам.")
        results = brute_force_search_files(query, top_n=top_n)

    return results


def perform_search(query: str, user_id: Optional[str] = None, top_n: int = 5) -> str:
    """
    Функция для роутера. Возвращает текстовое представление результатов поиска.
    """
    results = search_documents(query, user_id=user_id, top_n=top_n)

    if not results:
        return "❌ Ничего не найдено в ваших документах."

    lines = ["🔍 **Результаты поиска:**\n"]
    for i, doc in enumerate(results, 1):
        content_preview = doc["content"][:300]
        if len(doc["content"]) > 300:
            content_preview += "..."
        lines.append(
            f"📄 **{i}. {doc.get('filename', '(unnamed)')}** (chunk {doc.get('chunk_index', 0)})\n"
            f"{content_preview}\n"
        )

    return "\n".join(lines)