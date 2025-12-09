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
from tools.file_generator_tool import parse_llm_json, build_from_json

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


def _extract_and_apply_operations(llm_response: str, role: str = None) -> str:
    logger.info(f"Checking LLM response for JSON ({len(llm_response)} chars)")

    json_data = parse_llm_json(llm_response)

    if not json_data:
        logger.info("No valid JSON found in response")
        return llm_response

    if "sheets" in json_data:
        logger.info("Found file generation JSON")

        state = memory.get_state(role) or {}
        pending = state.get("pending_template_build", {})

        result = build_from_json(
            json_data,
            template_name=pending.get("template"),
            role=role
        )

        state["pending_template_build"] = None
        memory.set_state(role, state)

        if result.get("success"):
            explanation = _extract_explanation(llm_response)
            response = f"✅ Файл создан: {result['filename']}\n"
            response += f"📊 Листов: {result.get('sheets_count', 0)}, "
            response += f"Строк: {result.get('rows_count', 0)}\n"
            response += f"🔗 Скачать: {result['download_url']}"
            if explanation:
                response = f"{explanation}\n\n{response}"
            return response
        else:
            return f"{llm_response}\n\n❌ Ошибка создания файла: {result.get('error')}"

    if "operations" in json_data:
        logger.info("Found edit operations JSON")

        filename = json_data.get("filename")
        operations = json_data.get("operations", [])

        if not filename or not operations:
            logger.warning("Missing filename or operations")
            return llm_response

        logger.info(f"Applying {len(operations)} operations to: {filename}")

        result = edit_excel(filename, operations, role=role)

        if result.get("success"):
            explanation = _extract_explanation(llm_response)
            if explanation:
                return f"{explanation}\n\nГотово! Скачать: {result['download_url']}"
            else:
                return f"Файл отредактирован!\n\nСкачать: {result['download_url']}"
        else:
            return f"{llm_response}\n\nОшибка применения: {result.get('error')}"

    return llm_response


def _extract_explanation(response: str) -> str:
    json_start = response.find('```json')
    if json_start == -1:
        json_start = response.find('{')

    if json_start > 0:
        explanation = response[:json_start].strip()
        if explanation:
            return explanation

    return ""


async def agent_process(prompt: str, role: str):
    history = (memory.get_history(role) or [])[-MAX_HISTORY:]

    rag_context = ""
    if not _is_simple_message(prompt):
        logger.info(f"Running RAG search for: {prompt[:50]}...")
        rag_context = get_rag_context(prompt, role, top_n=10, max_context_chars=MAX_CONTEXT_CHARS)
        if rag_context:
            logger.info(f"RAG context: {len(rag_context)} chars")

    system_content = SYSTEM_PROMPT
    if rag_context:
        system_content += f"\n\n{rag_context}"

    messages = [{"role": "system", "content": system_content}] + history
    messages.append({"role": "user", "content": prompt})

    total_chars = sum(len(m["content"]) for m in messages)
    logger.info(f"Prompt: {total_chars} chars, ~{total_chars // 4} tokens")

    if vector_store.is_connected():
        vector_store.add_chat_message(prompt, "user", role)

    result, updated_messages = await route_message(messages, role)

    if result is None:
        llm_response = await send_to_llm(updated_messages)
        result = _extract_and_apply_operations(llm_response, role)

    if vector_store.is_connected():
        vector_store.add_chat_message(result, "assistant", role)

    new_history = history + [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": result}
    ]
    memory.set_history(role, new_history[-MAX_HISTORY:])

    return result