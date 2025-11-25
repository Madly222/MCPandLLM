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
MAX_HISTORY_MESSAGES = 10  # Максимум сообщений в истории
MAX_RAG_CONTEXT_CHARS = 4000  # Максимум символов RAG контекста
MAX_TOTAL_PROMPT_CHARS = 12000  # Общий лимит промпта
MAX_OUTPUT_TOKENS = 2048  # Токены на ответ


def _estimate_tokens(text: str) -> int:
    """Грубая оценка токенов (1 токен ≈ 4 символа для русского)"""
    return len(text) // 3


def _trim_history(history: list, max_messages: int = MAX_HISTORY_MESSAGES) -> list:
    """Обрезает историю, сохраняя последние сообщения"""
    if len(history) <= max_messages:
        return history

    # Всегда сохраняем системное сообщение если есть
    trimmed = history[-max_messages:]
    logger.info(f"📜 История обрезана: {len(history)} → {len(trimmed)} сообщений")
    return trimmed


def _trim_context(context: str, max_chars: int = MAX_RAG_CONTEXT_CHARS) -> str:
    """Обрезает RAG контекст"""
    if len(context) <= max_chars:
        return context

    trimmed = context[:max_chars] + "\n...[контекст обрезан из-за лимита]"
    logger.info(f"📄 Контекст обрезан: {len(context)} → {max_chars} символов")
    return trimmed


async def agent_process(prompt: str, user_id: str):
    # Получаем и обрезаем историю
    history = memory.get_history(user_id) or []
    history = _trim_history(history, MAX_HISTORY_MESSAGES)

    # Получаем и обрезаем RAG контекст
    rag_context = _build_rag_context(prompt, user_id)
    rag_context = _trim_context(rag_context, MAX_RAG_CONTEXT_CHARS)

    # Собираем системный промпт
    enhanced_system_prompt = SYSTEM_PROMPT
    if rag_context:
        enhanced_system_prompt += f"\n\n{rag_context}"

    # Проверяем общий размер
    messages = [{"role": "system", "content": enhanced_system_prompt}] + history
    messages.append({"role": "user", "content": prompt})

    total_chars = sum(len(m["content"]) for m in messages)

    # Если всё ещё слишком много — режем агрессивнее
    if total_chars > MAX_TOTAL_PROMPT_CHARS:
        logger.warning(f"⚠️ Промпт слишком большой ({total_chars} символов), обрезаем...")

        # Убираем RAG контекст
        if rag_context:
            enhanced_system_prompt = SYSTEM_PROMPT
            messages = [{"role": "system", "content": enhanced_system_prompt}] + history
            messages.append({"role": "user", "content": prompt})
            total_chars = sum(len(m["content"]) for m in messages)

        # Если всё ещё много — режем историю сильнее
        if total_chars > MAX_TOTAL_PROMPT_CHARS:
            history = history[-4:]  # Только последние 4 сообщения
            messages = [{"role": "system", "content": enhanced_system_prompt}] + history
            messages.append({"role": "user", "content": prompt})

    logger.info(f"📊 Размер промпта: ~{_estimate_tokens(str(messages))} токенов")

    if vector_store.is_connected():
        vector_store.add_chat_message(prompt, "user", user_id)

    result, updated_messages = await route_message(messages, user_id)

    if result is None:
        logger.info("Отправляем на LLM")
        result = await send_to_llm(updated_messages, max_tokens=MAX_OUTPUT_TOKENS)
        updated_messages.append({"role": "assistant", "content": result})

    if vector_store.is_connected():
        vector_store.add_chat_message(result, "assistant", user_id)

    # Сохраняем обрезанную историю
    memory.set_history(user_id, updated_messages[-MAX_HISTORY_MESSAGES:])
    return result


def _build_rag_context(query: str, user_id: str, max_length: int = MAX_RAG_CONTEXT_CHARS) -> str:
    """Собирает RAG контекст с учётом лимитов"""
    if not vector_store.is_connected():
        return ""

    try:
        context_parts = []

        # Документы — основной приоритет
        doc_context = get_rag_context(query, user_id, top_n=3)  # Уменьшил с 5 до 3
        if doc_context:
            context_parts.append(doc_context)

        # Память — только если есть место
        current_len = len("\n".join(context_parts))
        if current_len < max_length * 0.7:
            user_facts = vector_store.search_memory(query, user_id, limit=2)
            if user_facts:
                context_parts.append("\n=== ПАМЯТЬ ===")
                for fact in user_facts:
                    context_parts.append(f"• {fact}")

        # История чата — только если есть место
        current_len = len("\n".join(context_parts))
        if current_len < max_length * 0.8:
            chat_history = vector_store.search_chat_history(query, user_id, limit=2)
            if chat_history:
                context_parts.append("\n=== ИЗ ПРОШЛЫХ РАЗГОВОРОВ ===")
                for chat in chat_history:
                    msg = chat["message"][:150]
                    context_parts.append(f"• {msg}")

        full_context = "\n".join(context_parts)
        return full_context[:max_length]

    except Exception as e:
        logger.error(f"Ошибка RAG контекста: {e}")
        return ""