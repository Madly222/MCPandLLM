import logging
from typing import List, Dict, Optional

from vector_store import vector_store
from tools.search_tool import get_full_document_content, smart_search
from agent.models import send_to_llm

logger = logging.getLogger(__name__)

MAX_CONTEXT_PER_FILE = 15000
MAX_SUMMARY_LENGTH = 600
MAX_FILES_FOR_DIRECT = 3
MAX_TOTAL_CONTEXT = 45000


async def process_multiple_files(
        query: str,
        user_id: str,
        filenames: Optional[List[str]] = None,
        top_n: int = 10
) -> str:
    if filenames:
        docs = []
        for fname in filenames:
            doc = get_full_document_content(fname, user_id)
            if doc:
                docs.append(doc)
    else:
        search_results = smart_search(query, user_id, limit=top_n)
        seen = set()
        docs = []
        for r in search_results:
            fname = r.get("filename")
            if fname and fname not in seen:
                doc = get_full_document_content(fname, user_id)
                if doc:
                    docs.append(doc)
                    seen.add(fname)

    if not docs:
        return "Файлы не найдены."

    num_files = len(docs)
    logger.info(f"Найдено {num_files} файлов для обработки")

    if num_files <= MAX_FILES_FOR_DIRECT:
        return await _direct_processing(query, docs)
    else:
        return await _map_reduce_processing(query, docs)


async def _direct_processing(query: str, docs: List[Dict]) -> str:
    context_parts = ["# ДАННЫЕ ИЗ ФАЙЛОВ\n"]
    chars_per_file = MAX_TOTAL_CONTEXT // len(docs)

    for doc in docs:
        content = doc.get("content", "")[:chars_per_file]
        if len(doc.get("content", "")) > chars_per_file:
            content += "\n...[обрезано]"

        doc_type = "ТАБЛИЦА" if doc.get("is_table") else "ДОКУМЕНТ"
        filename = doc.get("filename", "unknown")
        context_parts.append(f"\n## [{doc_type}] {filename}\n\n{content}\n")

    full_context = "\n".join(context_parts)

    messages = [
        {"role": "system", "content": "Ты аналитик. Отвечай на основе предоставленных данных. Формат: markdown."},
        {"role": "user", "content": f"{full_context}\n\n**Задача:** {query}"}
    ]

    return await send_to_llm(messages)


async def _map_reduce_processing(query: str, docs: List[Dict]) -> str:
    summaries = []

    for doc in docs:
        content = doc.get("content", "")[:MAX_CONTEXT_PER_FILE]
        doc_type = "таблица" if doc.get("is_table") else "документ"
        filename = doc.get("filename", "unknown")

        map_messages = [
            {
                "role": "system",
                "content": f"Кратко опиши содержимое этого файла ({doc_type}) в контексте запроса. "
                           f"Максимум {MAX_SUMMARY_LENGTH} символов. Только факты."
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
                "is_table": doc.get("is_table", False)
            })
        except Exception as e:
            logger.error(f"Ошибка саммари {filename}: {e}")
            summaries.append({
                "filename": filename,
                "summary": f"[Ошибка: {e}]",
                "is_table": doc.get("is_table", False)
            })

    summaries_text = "\n\n".join([
        f"**{s['filename']}** ({'таблица' if s['is_table'] else 'документ'}):\n{s['summary']}"
        for s in summaries
    ])

    reduce_messages = [
        {
            "role": "system",
            "content": "На основе саммари файлов дай итоговый ответ. Структурируй информацию."
        },
        {
            "role": "user",
            "content": f"**Запрос:** {query}\n\n**Саммари файлов:**\n{summaries_text}"
        }
    ]

    final_response = await send_to_llm(reduce_messages)
    sources = ", ".join([s["filename"] for s in summaries])
    return f"{final_response}\n\n---\n*Источники: {sources}*"


async def summarize_all_user_files(user_id: str) -> str:
    return await process_multiple_files(
        query="Дай общую сводку по всем файлам. Что в них содержится?",
        user_id=user_id,
        top_n=50
    )


async def compare_files(filenames: List[str], user_id: str, aspect: str = "") -> str:
    query = f"Сравни эти файлы"
    if aspect:
        query += f" по критерию: {aspect}"

    return await process_multiple_files(
        query=query,
        user_id=user_id,
        filenames=filenames
    )