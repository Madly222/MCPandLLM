# tools/search_tool.py
import logging
from typing import List, Dict, Any
from vector_store import vector_store

logger = logging.getLogger(__name__)

# ============================================================
#  SEARCH PIPELINE 2.0:
#  1) Поиск по summary (очень точный)
#  2) Поиск по основным чанкам
#  3) Rerank
#  4) Формирование ответа
# ============================================================


def _score_boost_based_on_metadata(item: dict) -> float:
    """
    Даём бонус summary-чанкам, чтобы они были выше.
    """
    meta = item.get("metadata", {})

    if meta.get("type") == "summary":
        return 2.0    # summary намного важнее

    if meta.get("chunk_index") == 0:
        return 1.2    # первый чанк файла важнее

    return 1.0


def _rerank(results: List[dict]) -> List[dict]:
    """Улучшенная сортировка результатов поиска"""

    def calc_score(item: dict):
        score = item.get("score", 0)
        score *= _score_boost_based_on_metadata(item)
        return score

    return sorted(results, key=calc_score, reverse=True)


def _merge_results_by_file(results: List[dict]) -> Dict[str, List[dict]]:
    """Группируем результаты по файлам для более чистой выдачи."""
    grouped = {}

    for item in results:
        f = item.get("filename", "UNKNOWN")
        grouped.setdefault(f, []).append(item)

    return grouped


def _format_final_answer(grouped: Dict[str, List[dict]]) -> str:
    """Формирование сообщения для пользователя"""

    if not grouped:
        return "Ничего не найдено."

    blocks = []

    for filename, items in grouped.items():
        blocks.append(f"\n📄 **{filename}**")

        for item in items[:3]:  # максимум 3 чанка на файл
            meta = item.get("metadata", {})
            chunk_id = meta.get("chunk_index")
            text = item.get("content", "")[:500]

            if meta.get("type") == "summary":
                blocks.append(f"🟦 *Summary:* \n{text}\n")
            else:
                blocks.append(f"🔹 Чанк {chunk_id}:\n{text}\n")

    return "\n".join(blocks)


# ====================================================================
#  MAIN SEARCH FUNCTION
# ====================================================================

def search(query: str, user_id: str = "default", limit: int = 12) -> str:
    """
    Улучшенный интеллектуальный поиск по файлам.
    1) Сначала summary
    2) Потом обычные чанки
    3) Затем rerank результатов
    """

    if not query or len(query.strip()) < 2:
        return "Введите более конкретный запрос."

    if not vector_store.is_connected():
        if not vector_store.connect():
            return "❌ Ошибка подключения к векторному хранилищу."

    try:
        # === 1. Поиск по summary ==================================================
        summary_res = vector_store.search(
            query=query,
            user_id=user_id,
            limit=limit,
            filters={"type": "summary"}
        )

        # === 2. Поиск по основным чанкам =========================================
        chunk_res = vector_store.search(
            query=query,
            user_id=user_id,
            limit=limit
        )

        # === 3. Объединяем ========================================================
        combined = (summary_res or []) + (chunk_res or [])

        if not combined:
            return "По запросу ничего не найдено."

        # === 4. RERANK ============================================================
        reranked = _rerank(combined)

        # === 5. Группировка по файлам ============================================
        grouped = _merge_results_by_file(reranked)

        # === 6. Формируем удобный и читабельный ответ ============================
        return _format_final_answer(grouped)

    except Exception as e:
        logger.error(f"❌ Ошибка поиска: {e}")
        return "Ошибка поиска."