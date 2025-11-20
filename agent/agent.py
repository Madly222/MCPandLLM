from agent.memory import memory
from agent.router import route_message
from agent.prompts import SYSTEM_PROMPT
from agent.models import send_to_llm
from vector_store import vector_store


async def agent_process(prompt: str, user_id: str):
    """
    Основной процесс агента с RAG (Retrieval Augmented Generation):
    - Загружает историю сообщений пользователя
    - Ищет релевантный контекст в векторной БД (RAG)
    - Добавляет системный и пользовательский промпт
    - Отправляет на роутер, который может обработать команды файлов или Excel
    - Если роутер не дал результата, вызывает LLM с контекстом
    - Сохраняет сообщения в векторную БД для долговременной памяти
    - Обновляет историю
    """
    history = memory.get_history(user_id) or []

    # === RAG: Поиск релевантного контекста ===
    rag_context = _get_rag_context(prompt, user_id)

    # Формируем системный промпт с контекстом
    enhanced_system_prompt = SYSTEM_PROMPT
    if rag_context:
        enhanced_system_prompt += f"\n\n📚 **Релевантный контекст из документов:**\n{rag_context}"

    messages = [{"role": "system", "content": enhanced_system_prompt}] + history
    messages.append({"role": "user", "content": prompt})

    # Сохраняем пользовательское сообщение в векторную БД
    if vector_store.is_connected():
        vector_store.add_chat_message(prompt, "user", user_id)

    result, updated_messages = await route_message(messages, user_id)

    if result is None:
        result = await send_to_llm(updated_messages)
        updated_messages.append({"role": "assistant", "content": result})

    # Сохраняем ответ ассистента в векторную БД
    if vector_store.is_connected():
        vector_store.add_chat_message(result, "assistant", user_id)

    # Храним последние 50 сообщений для мягкого ограничения истории
    memory.set_history(user_id, updated_messages[-50:])
    return result


def _get_rag_context(query: str, user_id: str, max_length: int = 2000) -> str:
    """
    Получение релевантного контекста для RAG

    Args:
        query: Запрос пользователя
        user_id: ID пользователя
        max_length: Максимальная длина контекста

    Returns:
        Строка с релевантным контекстом
    """
    if not vector_store.is_connected():
        return ""

    try:
        context_parts = []

        # 1. Поиск в документах
        doc_results = vector_store.search_documents(query, user_id, limit=3)
        if doc_results:
            context_parts.append("**Из ваших документов:**")
            for doc in doc_results:
                content_preview = doc["content"][:300]
                if len(doc["content"]) > 300:
                    content_preview += "..."
                context_parts.append(f"• [{doc['filename']}]: {content_preview}")

        # 2. Поиск фактов о пользователе
        user_facts = vector_store.search_memory(query, user_id, limit=2)
        if user_facts:
            context_parts.append("\n**Что я знаю о вас:**")
            for fact in user_facts:
                context_parts.append(f"• {fact}")

        # 3. Поиск в истории чатов
        chat_history = vector_store.search_chat_history(query, user_id, limit=2)
        if chat_history:
            context_parts.append("\n**Из прошлых разговоров:**")
            for chat in chat_history:
                message_preview = chat["message"][:200]
                if len(chat["message"]) > 200:
                    message_preview += "..."
                context_parts.append(f"• {message_preview}")

        full_context = "\n".join(context_parts)

        # Обрезаем если слишком длинный
        if len(full_context) > max_length:
            full_context = full_context[:max_length] + "..."

        return full_context

    except Exception as e:
        print(f"Ошибка получения RAG контекста: {e}")
        return ""