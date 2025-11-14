from agent.memory import memory
from agent.router import route_message
from agent.prompts import SYSTEM_PROMPT
from .models import send_to_llm

async def agent_process(prompt: str, user_id: str):
    """
    Основной процесс агента:
    - Загружает историю сообщений пользователя
    - Добавляет системный и пользовательский промпт
    - Отправляет на роутер, который может обработать команды файлов или Excel
    - Если роутер не дал результата, вызывает LLM
    - Обновляет историю
    """
    history = memory.get_history(user_id) or []
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    messages.append({"role": "user", "content": prompt})

    result, updated_messages = await route_message(messages, user_id)

    if result is None:
        result = await send_to_llm(updated_messages)
        updated_messages.append({"role": "assistant", "content": result})

    # Храним последние 50 сообщений для мягкого ограничения истории
    memory.set_history(user_id, updated_messages[-50:])
    return result
