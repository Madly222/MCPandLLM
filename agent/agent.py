# agent/agent.py
from agent.memory import memory
from agent.router import route_message
from agent.prompts import SYSTEM_PROMPT
from agent.models import send_to_llm
from vector_store import vector_store
from tools.search_tool import get_rag_context
import re
import logging

logger = logging.getLogger(__name__)

# === ЛИМИТЫ ===
MAX_HISTORY_MESSAGES = 10
MAX_RAG_CONTEXT_CHARS = 5000


def _filter_user_assistant(messages: list) -> list:
    """Возвращает только сообщения ролей 'user' и 'assistant'"""
    return [m for m in messages if m.get("role") in ("user", "assistant")]


def _needs_rag_context(query: str) -> bool:
    """
    Определяет, нужен ли RAG контекст для запроса.
    RAG нужен ТОЛЬКО если есть явные триггеры.
    """
    query_lower = query.lower().strip()

    # Простые сообщения — НЕ нужен RAG
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
            logger.info("⏭️ RAG пропущен: простое сообщение")
            return False

    # Явные триггеры — НУЖЕН RAG
    rag_triggers = [
        r'(файл|таблиц|документ|excel|xlsx|данные|отчёт|отчет)',
        r'(найди|поиск|покажи|открой|прочитай)',
        r'(сколько|итого|сумма|цена|стоимость)',
        r'(список|перечень|все\s)',
        r'(micb|глодень|армянская)',
    ]

    for pattern in rag_triggers:
        if re.search(pattern, query_lower):
            logger.info("✅ RAG нужен: найден триггер")
            return True

    # По умолчанию — НЕ нужен RAG
    logger.info("⏭️ RAG пропущен: нет триггеров")
    return False


async def agent_process(prompt: str, user_id: str):
    # История — только последние сообщения
    history = (memory.get_history(user_id) or [])[-MAX_HISTORY_MESSAGES:]

    # RAG контекст — только если нужен
    rag_context = ""
    if _needs_rag_context(prompt):
        rag_context = _build_rag_context(prompt, user_id)

    # Собираем промпт
    system_content = SYSTEM_PROMPT
    if rag_context:
        system_content += f"\n\n{rag_context}"

    messages = [{"role": "system", "content": system_content}] + history
    messages.append({"role": "user", "content": prompt})

    # Логируем размер
    total_chars = sum(len(m["content"]) for m in messages)
    logger.info(f"📊 Промпт: {total_chars} символов, ~{total_chars // 3} токенов")

    # Сохраняем в векторное хранилище
    if vector_store.is_connected():
        vector_store.add_chat_message(prompt, "user", user_id)

    # Роутер
    result, updated_messages = await route_message(messages, user_id)

    # Если роутер не обработал — LLM
    if result is None:
        if result is None:
            import json
            try:
                pretty = json.dumps(messages, ensure_ascii=False, indent=2)
                logger.info(
                    "\n========== FULL PROMPT BEGIN ==========\n" + pretty + "\n========== FULL PROMPT END ==========\n")
                print("\n========== FULL PROMPT BEGIN ==========")
                print(pretty)
                print("========== FULL PROMPT END ==========\n")
            except Exception as e:
                logger.error(f"❌ Failed to dump full prompt: {e}")
        result = await send_to_llm(messages)

    # Сохраняем ответ
    if vector_store.is_connected():
        vector_store.add_chat_message(result, "assistant", user_id)

    # Сохраняем историю
    new_entries = [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": result}
    ]
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

        # Память
        facts = vector_store.search_memory(query, user_id, limit=2)
        if facts:
            parts.append("=== ПАМЯТЬ ===\n" + "\n".join(f"• {f}" for f in facts))

        result = "\n\n".join(parts)
        return result[:MAX_RAG_CONTEXT_CHARS]

    except Exception as e:
        logger.error(f"Ошибка RAG: {e}")
        return ""