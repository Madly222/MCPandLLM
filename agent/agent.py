import re
import json
import logging

from agent.memory import memory
from agent.router import route_message
from agent.prompts import SYSTEM_PROMPT
from agent.models import send_to_llm
from vector_store import vector_store
from tools.search_tool import get_rag_context
from tools.edit_excel_tool import edit_excel

logger = logging.getLogger(__name__)

MAX_HISTORY = 10
MAX_CONTEXT_CHARS = 60000


def _is_simple_message(query: str) -> bool:
    query_lower = query.lower().strip()

    simple = [
        r'^(привет|здравствуй|добрый день|добрый вечер|доброе утро|хай|hello|hi|hey)[\s!.?]*$',
        r'^(пока|до свидания|bye|goodbye)[\s!.?]*$',
        r'^(спасибо|благодарю|thanks|thank you)[\s!.?]*$',
        r'^(да|нет|ок|okay|ok|хорошо|понял|ясно|угу)[\s!.?]*$',
        r'^(как дела|как ты|что нового)[\s?]*$',
        r'^(кто ты|что ты|помощь|help)[\s?]*$',
    ]

    for p in simple:
        if re.match(p, query_lower):
            return True
    return False


def _extract_and_apply_json_operations(llm_response: str) -> str:
    edit_match = re.search(
        r'```json\s*(\{[\s\S]*?"operations"[\s\S]*?\})\s*```',
        llm_response,
        re.I
    )

    if not edit_match:
        return llm_response

    try:
        edit_data = json.loads(edit_match.group(1))
        filename = edit_data.get("filename")
        operations = edit_data.get("operations", [])

        if not filename or not operations:
            return llm_response

        logger.info(f"Применяем {len(operations)} операций к файлу {filename}")

        result = edit_excel(filename, operations)

        if result.get("success"):
            explanation = llm_response[:edit_match.start()].strip()
            if explanation:
                return f"{explanation}\n\nГотово! Скачать: {result['download_url']}"
            else:
                return f"Файл отредактирован!\n\nСкачать: {result['download_url']}"
        else:
            return f"{llm_response}\n\nОшибка применения: {result.get('error')}"

    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга JSON из ответа LLM: {e}")
        return llm_response
    except Exception as e:
        logger.error(f"Ошибка применения операций: {e}")
        return f"{llm_response}\n\nОшибка: {e}"


async def agent_process(prompt: str, user_id: str):
    history = (memory.get_history(user_id) or [])[-MAX_HISTORY:]

    rag_context = ""
    if not _is_simple_message(prompt):
        logger.info(f"Запускаем RAG поиск для: {prompt[:50]}...")
        rag_context = get_rag_context(prompt, user_id, top_n=10, max_chars=MAX_CONTEXT_CHARS)
        if rag_context:
            logger.info(f"RAG контекст: {len(rag_context)} символов")
        else:
            logger.info("RAG: ничего не найдено")
    else:
        logger.info("Простое сообщение, RAG пропущен")

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
        llm_response = await send_to_llm(updated_messages)
        result = _extract_and_apply_json_operations(llm_response)

    if vector_store.is_connected():
        vector_store.add_chat_message(result, "assistant", user_id)

    new_history = history + [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": result}
    ]
    memory.set_history(user_id, new_history[-MAX_HISTORY:])

    return result