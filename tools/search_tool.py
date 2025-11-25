import logging
from pathlib import Path
from typing import List, Dict, Optional

from vector_store import vector_store  # ✅ Используем глобальный
from tools.utils import BASE_FILES_DIR
from tools.file_tool import read_file
from tools.excel_tool import read_excel

logger = logging.getLogger(__name__)


def keyword_search_in_files(query: str, top_n: int = 5) -> List[Dict]:
    """Прямой поиск подстроки в файлах (fallback)"""
    hits = []
    query_lower = query.lower()

    for filepath in BASE_FILES_DIR.iterdir():
        if not filepath.is_file():
            continue

        try:
            # Читаем содержимое
            if filepath.suffix.lower() in ['.xlsx', '.xls']:
                content = read_excel(filepath.name)
            else:
                content = read_file(filepath)

            if not content or str(content).startswith(("Ошибка", "Файл")):
                continue

            content_lower = content.lower()

            # Ищем все вхождения
            start = 0
            while True:
                pos = content_lower.find(query_lower, start)
                if pos == -1:
                    break

                # Извлекаем контекст вокруг найденного
                context_start = max(0, pos - 150)
                context_end = min(len(content), pos + len(query) + 150)
                snippet = content[context_start:context_end].replace("\n", " ").strip()

                hits.append({
                    "filename": filepath.name,
                    "filetype": filepath.suffix.lstrip('.'),
                    "content": snippet,
                    "score": 1.0,
                    "match_type": "keyword"
                })

                if len(hits) >= top_n:
                    return hits

                start = pos + 1

        except Exception as e:
            logger.error(f"Ошибка поиска в {filepath.name}: {e}")
            continue

    return hits


def semantic_search(query: str, user_id: str = "default", limit: int = 10) -> List[Dict]:

    """caca"""
    user_id = "default"
    """caca"""

    """Семантический поиск через Weaviate"""
    if not vector_store.is_connected():
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
    """Гибридный поиск: semantic + keyword"""

    """caca"""
    user_id = "default"
    """caca"""

    # 1. Семантический поиск (топ-10)
    semantic_results = semantic_search(query, user_id, limit=10)

    # 2. Если семантика дала мало результатов, добавляем keyword
    if len(semantic_results) < 3:
        logger.info("Дополняем keyword поиском...")
        keyword_results = keyword_search_in_files(query, top_n=5)

        # Объединяем, избегая дубликатов
        seen_files = {r["filename"] for r in semantic_results}
        for kr in keyword_results:
            if kr["filename"] not in seen_files:
                semantic_results.append(kr)
                seen_files.add(kr["filename"])

    # 3. Ранжируем: semantic результаты выше
    semantic_results.sort(key=lambda x: 0 if x["match_type"] == "semantic" else 1)

    return semantic_results[:top_n]


def search_documents(query: str, user_id: str = "default", top_n: int = 5) -> str:
    """Главная функция поиска для router"""

    """caca"""
    user_id = "default"
    """caca"""

    # Используем гибридный поиск
    results = hybrid_search(query, user_id, top_n)

    if not results:
        return "❌ Ничего не найдено в документах."

    # Форматируем результаты
    lines = ["🔍 **Результаты поиска:**\n"]

    for i, doc in enumerate(results, 1):
        content_preview = doc["content"][:300]
        if len(doc["content"]) > 300:
            content_preview += "..."

        match_type = "🎯 семантика" if doc.get("match_type") == "semantic" else "🔍 ключевое слово"

        lines.append(
            f"📄 **{i}. {doc['filename']}** ({doc.get('filetype', '?')}) {match_type}\n"
            f"{content_preview}\n"
        )

    return "\n".join(lines)

def perform_search(query: str, user_id: str = "default", top_n: int = 5):
    """
    Старый alias для совместимости с router.py.
    Использует гибридный поиск.
    """

    """caca"""
    user_id = "default"
    """caca"""
    
    return search_documents(query, user_id, top_n)
