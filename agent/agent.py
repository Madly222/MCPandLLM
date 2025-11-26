# agent/agent.py
from agent.memory import memory
from agent.router import route_message
from agent.prompts import SYSTEM_PROMPT
from agent.models import send_to_llm
from vector_store import vector_store
from tools.search_tool import get_rag_context
import logging

logger = logging.getLogger(__name__)

# === ЛИМИТЫ ===
MAX_HISTORY_MESSAGES = 10
MAX_RAG_CONTEXT_CHARS = 5000


def _filter_user_assistant(messages: list) -> list:
    """
    Возвращает только сообщения ролей 'user' и 'assistant' в том же порядке.
    """
    return [m for m in messages if m.get("role") in ("user", "assistant")]


async def agent_process(prompt: str, user_id: str):
    # История — только последние сообщения (user/assistant)
    memory.clear_all_history()

    history = (memory.get_history(user_id) or [])[-MAX_HISTORY_MESSAGES:]

    # RAG контекст
    rag_context = _build_rag_context(prompt, user_id)

    # Собираем промпт (system + rag если есть)
    system_content = SYSTEM_PROMPT
    if rag_context:
        system_content += f"\n\n{rag_context}"

    # messages для отправки в route/send
    messages = [{"role": "system", "content": system_content}] + history
    messages.append({"role": "user", "content": prompt})

    # Логируем размер
    total_chars = sum(len(m["content"]) for m in messages)
    logger.info(f"📊 Промпт: {total_chars} символов, ~{total_chars // 3} токенов")

    # Сохраняем пользовательское сообщение в векторное хранилище (если нужно)
    if vector_store.is_connected():
        vector_store.add_chat_message(prompt, "user", user_id)

    # route_message может вернуть (assistant_text, updated_messages) или (None, messages)
    result, updated_messages = await route_message(messages, user_id)

    # Если route_message не обработал — посылаем данные LLM
    if result is None:
        # Отправляем сейчас только messages (system + history + prompt)
        result = await send_to_llm(messages)

    # Сохраняем ответ в Vector DB
    if vector_store.is_connected():
        vector_store.add_chat_message(result, "assistant", user_id)

    # --- СОХРАНЕНИЕ ИСТОРИИ: только user/assistant, и максимум MAX_HISTORY_MESSAGES ---
    # Берём старую историю (history) + новый пары сообщений (user, assistant)
    new_entries = [{"role": "user", "content": prompt},
                   {"role": "assistant", "content": result}]

    combined = history + new_entries
    filtered = _filter_user_assistant(combined)
    memory.set_history(user_id, filtered[-MAX_HISTORY_MESSAGES:])

    return result


def _build_rag_context(query: str, user_id: str) -> str:
    """Компактный RAG контекст"""
    if not vector_store.is_connected():
        return ""

    try:
        parts = []

        # Документы
        doc_context = get_rag_context(query, user_id, top_n=3)
        if doc_context:
            parts.append(doc_context)

        # Память (коротко)
        facts = vector_store.search_memory(query, user_id, limit=2)
        if facts:
            parts.append("=== ПАМЯТЬ ===\n" + "\n".join(f"• {f}" for f in facts))

        result = "\n\n".join(parts)
        return result[:MAX_RAG_CONTEXT_CHARS]

    except Exception as e:
        logger.error(f"Ошибка RAG: {e}")
        return ""