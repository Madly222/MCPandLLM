from agent.memory import memory
from agent.router import route_message
from agent.prompts import SYSTEM_PROMPT
from .models import send_to_llm

async def agent_process(prompt: str, user_id: str):
    history = memory.get_history(user_id)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    messages.append({"role": "user", "content": prompt})

    result, updated_messages = await route_message(messages, user_id)

    if result is None:
        # вызываем асинхронный LLM клиент
        result = await send_to_llm(updated_messages)

    memory.set_history(user_id, updated_messages)
    return result