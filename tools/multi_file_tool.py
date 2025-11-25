# tools/multi_file_tool.py
import logging
from typing import List, Dict, Optional
from pathlib import Path

from vector_store import vector_store
from tools.search_tool import hybrid_search
from agent.models import send_to_llm

logger = logging.getLogger(__name__)

# Лимиты
MAX_CONTEXT_PER_FILE = 8000  # Символов на файл при обработке
MAX_SUMMARY_LENGTH = 500  # Длина саммари одного файла
MAX_FILES_FOR_DIRECT = 3  # До 3 файлов — передаём напрямую
MAX_TOTAL_CONTEXT = 30000  # Общий лимит контекста


async def process_multiple_files(
        query: str,
        user_id: str,
        filenames: Optional[List[str]] = None,
        top_n: int = 10
) -> str:
    """
    Обработка нескольких файлов с автоматическим выбором стратегии.

    - До 3 файлов: передаём контент напрямую
    - 4+ файлов: Map-Reduce (саммари каждого → итоговая сводка)
    """

    # Получаем файлы
    if filenames:
        # Конкретные файлы по именам
        docs = _get_files_by_names(filenames, user_id)
    else:
        # Поиск релевантных файлов
        docs = hybrid_search(query, user_id, top_n=top_n)

    if not docs:
        return "❌ Файлы не найдены."

    # Группируем чанки по файлам
    files_content = _group_by_filename(docs)
    num_files = len(files_content)

    logger.info(f"📁 Найдено {num_files} файлов для обработки")

    # Выбор стратегии
    if num_files <= MAX_FILES_FOR_DIRECT:
        return await _direct_processing(query, files_content)
    else:
        return await _map_reduce_processing(query, files_content)


def _get_files_by_names(filenames: List[str], user_id: str) -> List[Dict]:
    """Получение документов по именам файлов"""
    if not vector_store.is_connected():
        return []

    all_docs = []
    for filename in filenames:
        # Поиск по имени файла
        results = vector_store.search_documents(filename, user_id, limit=5)
        # Фильтруем по точному имени
        for doc in results:
            if doc.get("filename", "").lower() == filename.lower():
                all_docs.append(doc)

    return all_docs


def _group_by_filename(docs: List[Dict]) -> Dict[str, Dict]:
    """
    Группирует чанки по файлам.
    Возвращает: {filename: {"content": str, "is_table": bool, "chunks": int}}
    """
    files = {}

    for doc in docs:
        filename = doc.get("filename", "unknown")

        if filename not in files:
            files[filename] = {
                "content": "",
                "is_table": doc.get("is_table", False),
                "filetype": doc.get("filetype", ""),
                "chunks": 0
            }

        files[filename]["content"] += doc.get("content", "") + "\n"
        files[filename]["chunks"] += 1

    return files


async def _direct_processing(query: str, files_content: Dict[str, Dict]) -> str:
    """
    Прямая обработка (для малого количества файлов).
    Передаём весь контент в LLM.
    """
    context_parts = ["=== ДАННЫЕ ИЗ ФАЙЛОВ ===\n"]

    total_chars = 0
    chars_per_file = MAX_TOTAL_CONTEXT // len(files_content)

    for filename, data in files_content.items():
        content = data["content"][:chars_per_file]
        if len(data["content"]) > chars_per_file:
            content += "\n...[обрезано]"

        doc_type = "ТАБЛИЦА" if data["is_table"] else "ДОКУМЕНТ"
        context_parts.append(f"--- [{doc_type}] {filename} ---\n{content}\n")
        total_chars += len(content)

    full_context = "\n".join(context_parts)

    messages = [
        {"role": "system", "content": "Ты аналитик. Отвечай на основе предоставленных данных."},
        {"role": "user", "content": f"{full_context}\n\n**Задача:** {query}"}
    ]

    return await send_to_llm(messages)


async def _map_reduce_processing(query: str, files_content: Dict[str, Dict]) -> str:
    """
    Map-Reduce обработка (для большого количества файлов).
    1. Map: получаем саммари каждого файла
    2. Reduce: объединяем саммари в итоговый ответ
    """

    # === MAP: Саммари каждого файла ===
    summaries = []

    for filename, data in files_content.items():
        content = data["content"][:MAX_CONTEXT_PER_FILE]
        doc_type = "таблица" if data["is_table"] else "документ"

        map_messages = [
            {
                "role": "system",
                "content": f"Кратко опиши содержимое этого файла ({doc_type}) в контексте запроса. "
                           f"Максимум {MAX_SUMMARY_LENGTH} символов. Только факты, без воды."
            },
            {
                "role": "user",
                "content": f"**Файл:** {filename}\n**Запрос:** {query}\n\n**Содержимое:**\n{content}"
            }
        ]

        try:
            summary = await send_to_llm(map_messages)
            summaries.append({
                "filename": filename,
                "summary": summary[:MAX_SUMMARY_LENGTH],
                "is_table": data["is_table"]
            })
            logger.info(f"✅ Саммари для {filename} готово")
        except Exception as e:
            logger.error(f"❌ Ошибка саммари {filename}: {e}")
            summaries.append({
                "filename": filename,
                "summary": f"[Ошибка обработки: {e}]",
                "is_table": data["is_table"]
            })

    # === REDUCE: Итоговая сводка ===
    summaries_text = "\n\n".join([
        f"📄 **{s['filename']}** ({'таблица' if s['is_table'] else 'документ'}):\n{s['summary']}"
        for s in summaries
    ])

    reduce_messages = [
        {
            "role": "system",
            "content": "На основе саммари нескольких файлов дай итоговый ответ на запрос пользователя. "
                       "Структурируй информацию, выдели ключевые моменты."
        },
        {
            "role": "user",
            "content": f"**Запрос:** {query}\n\n**Саммари файлов:**\n{summaries_text}"
        }
    ]

    final_response = await send_to_llm(reduce_messages)

    # Добавляем информацию об источниках
    sources = ", ".join([s["filename"] for s in summaries])
    return f"{final_response}\n\n---\n📁 *Источники: {sources}*"


async def summarize_all_user_files(user_id: str) -> str:
    """Сводка по ВСЕМ файлам пользователя"""
    return await process_multiple_files(
        query="Дай общую сводку по всем файлам. Что в них содержится?",
        user_id=user_id,
        top_n=50
    )


async def compare_files(filenames: List[str], user_id: str, aspect: str = "") -> str:
    """Сравнение конкретных файлов"""
    query = f"Сравни эти файлы"
    if aspect:
        query += f" по критерию: {aspect}"

    return await process_multiple_files(
        query=query,
        user_id=user_id,
        filenames=filenames
    )