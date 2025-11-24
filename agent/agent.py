# agent/agent.py
from agent.memory import memory
from agent.router import route_message
from agent.prompts import SYSTEM_PROMPT
from agent.models import send_to_llm
from vector_store import vector_store
import logging

logger = logging.getLogger(__name__)

DOC_INDEX_USER_ID = "shared"  # Общий индекс для всех документов

async def agent_process(prompt: str, user_id: str):
    history = memory.get_history(user_id) or []

    rag_context = _get_rag_context(prompt)

    enhanced_system_prompt = SYSTEM_PROMPT
    if rag_context:
        enhanced_system_prompt += f"\n\n📚 **Релевантный контекст из документов:**\n{rag_context}"

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


def _get_rag_context(query: str, max_length: int = 2000) -> str:
    """Получение контекста из общих документов и памяти пользователя"""
    if not vector_store.is_connected():
        return ""

    try:
        context_parts = []

        # Поиск по общему индексу документов
        doc_results = vector_store.search_documents(query, DOC_INDEX_USER_ID, limit=3)
        if doc_results:
            context_parts.append("**Из документов:**")
            for doc in doc_results:
                content_preview = doc["content"][:300]
                if len(doc["content"]) > 300:
                    content_preview += "..."
                context_parts.append(f"• [{doc['filename']}]: {content_preview}")

        # Поиск по памяти пользователя
        user_facts = vector_store.search_memory(query, DOC_INDEX_USER_ID, limit=2)
        if user_facts:
            context_parts.append("\n**Что я знаю о вас:**")
            for fact in user_facts:
                context_parts.append(f"• {fact}")

        # Прошлые сообщения пользователя
        chat_history = vector_store.search_chat_history(query, DOC_INDEX_USER_ID, limit=2)
        if chat_history:
            context_parts.append("\n**Из прошлых разговоров:**")
            for chat in chat_history:
                message_preview = chat["message"][:200]
                if len(chat["message"]) > 200:
                    message_preview += "..."
                context_parts.append(f"• {message_preview}")

        full_context = "\n".join(context_parts)
        if len(full_context) > max_length:
            full_context = full_context[:max_length] + "..."
        return full_context

    except Exception as e:
        logger.error(f"Ошибка получения RAG контекста: {e}")
        return ""