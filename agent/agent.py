# agent/agent.py
from agent.memory import memory
from agent.router import route_message
from agent.prompts import SYSTEM_PROMPT
from agent.models import send_to_llm
from vector_store import vector_store
from tools.search_tool import get_rag_context  # ✅ Используем готовую функцию
import logging

logger = logging.getLogger(__name__)


async def agent_process(prompt: str, user_id: str):
    history = memory.get_history(user_id) or []

    # ✅ Используем тот же user_id для поиска
    rag_context = _build_rag_context(prompt, user_id)

    enhanced_system_prompt = SYSTEM_PROMPT
    if rag_context:
        enhanced_system_prompt += f"\n\n{rag_context}"

    messages = [{"role": "system", "content": enhanced_system_prompt}] + history
    messages.append({"role": "user", "content": prompt})

    if vector_store.is_connected():
        vector_store.add_chat_message(prompt, "user", user_id)

    result, updated_messages = await route_message(messages, user_id)

    if result is None:
        logger.info("Отправляем на LLM с контекстом")
        result = await send_to_llm(updated_messages)
        updated_messages.append({"role": "assistant", "content": result})

    if vector_store.is_connected():
        vector_store.add_chat_message(result, "assistant", user_id)

    memory.set_history(user_id, updated_messages[-50:])
    return result


def _build_rag_context(query: str, user_id: str, max_length: int = 15000) -> str:
    """Собирает полный RAG контекст: документы + память + история"""
    if not vector_store.is_connected():
        return ""

    try:
        context_parts = []

        # 1. Контекст из документов (используем функцию из search_tool)
        doc_context = get_rag_context(query, user_id, top_n=5)
        if doc_context:
            context_parts.append(doc_context)

        # 2. Память пользователя
        user_facts = vector_store.search_memory(query, user_id, limit=3)
        if user_facts:
            context_parts.append("\n=== ЧТО Я ЗНАЮ О ПОЛЬЗОВАТЕЛЕ ===")
            for fact in user_facts:
                context_parts.append(f"• {fact}")

        # 3. Релевантная история чата
        chat_history = vector_store.search_chat_history(query, user_id, limit=3)
        if chat_history:
            context_parts.append("\n=== ИЗ ПРОШЛЫХ РАЗГОВОРОВ ===")
            for chat in chat_history:
                role = "Пользователь" if chat["role"] == "user" else "Ассистент"
                msg = chat["message"][:200]
                if len(chat["message"]) > 200:
                    msg += "..."
                context_parts.append(f"[{role}]: {msg}")

        full_context = "\n".join(context_parts)

        if len(full_context) > max_length:
            full_context = full_context[:max_length] + "\n...[контекст обрезан]"

        return full_context

    except Exception as e:
        logger.error(f"Ошибка получения RAG контекста: {e}")
        return ""