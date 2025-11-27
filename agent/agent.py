from agent.memory import memory
from agent.router import route_message
from agent.prompts import SYSTEM_PROMPT
from agent.models import send_to_llm
from vector_store import vector_store
from tools.search_tool import get_rag_context, get_rag_context_for_summary, needs_full_context
import re
import logging

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 5
MAX_RAG_CONTEXT_CHARS = 25000
MAX_RAG_SUMMARY_CHARS = 40000


def _filter_user_assistant(messages: list) -> list:
    return [m for m in messages if m.get("role") in ("user", "assistant")]


def _needs_rag_context(query: str) -> bool:
    query_lower = query.lower().strip()

    simple_patterns = [
        r'^(привет|здравствуй|добрый день|добрый вечер|доброе утро|хай|hello|hi)[\s!.?]*$',
        r'^(пока|до свидания|bye|goodbye)[\s!.?]*$',
        r'^(спасибо|благодарю|thanks|thank you)[\s!.?]*$',
        r'^(да|нет|ок|okay|ok|хорошо|понял|ясно)[\s!.?]*$',
        r'^(как дела|как ты|что нового|что делаешь)[\s?]*$',
        r'^(кто ты|что ты умеешь|помощь|help)[\s?]*$',
    ]

    for pattern in simple_patterns:
        if re.match(pattern, query_lower):
            return False

    rag_triggers = [
        r'(файл|таблиц|документ|excel|xlsx|данные|отчёт|отчет|перечисли)',
        r'(найди|поиск|покажи|открой|прочитай)',
        r'(сколько|итого|сумма|цена|стоимость)',
        r'(список|перечень|все\s|сводка|обзор)',
        r'(проект|материал|товар|позиц|проекты)',
    ]

    for pattern in rag_triggers:
        if re.search(pattern, query_lower):
            return True

    return False


async def agent_process(prompt: str, user_id: str):
    history = (memory.get_history(user_id) or [])[-MAX_HISTORY_MESSAGES:]

    rag_context = ""
    if _needs_rag_context(prompt):
        rag_context = _build_rag_context(prompt, user_id)

    system_content = SYSTEM_PROMPT
    if rag_context:
        system_content += f"\n\n{rag_context}"

    messages = [{"role": "system", "content": system_content}] + history
    messages.append({"role": "user", "content": prompt})

    total_chars = sum(len(m["content"]) for m in messages)
    logger.info(f"Промпт: {total_chars} символов, ~{total_chars // 4} токенов")

    if vector_store.is_connected():
        vector_store.add_chat_message(prompt, "user", user_id)

    result, updated_messages = await route_message(messages, user_id)

    if result is None:
        result = await send_to_llm(messages)

    if vector_store.is_connected():
        vector_store.add_chat_message(result, "assistant", user_id)

    new_entries = [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": result}
    ]
    combined = history + new_entries
    filtered = _filter_user_assistant(combined)
    memory.set_history(user_id, filtered[-MAX_HISTORY_MESSAGES:])

    return result


def _build_rag_context(query: str, user_id: str) -> str:
    if not vector_store.is_connected():
        return ""

    try:
        parts = []

        if needs_full_context(query):
            doc_context = get_rag_context_for_summary(query, user_id, max_chars=MAX_RAG_SUMMARY_CHARS)
        else:
            doc_context = get_rag_context(query, user_id, top_n=5, max_context_chars=MAX_RAG_CONTEXT_CHARS)

        if doc_context:
            parts.append(doc_context)

        facts = vector_store.search_memory(query, user_id, limit=3)
        if facts:
            parts.append("# ПАМЯТЬ\n" + "\n".join(f"- {f}" for f in facts))

        return "\n\n".join(parts)

    except Exception as e:
        logger.error(f"Ошибка RAG: {e}")
        return ""