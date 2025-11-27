import os
from dotenv import load_dotenv
import anthropic
import asyncio
import logging

load_dotenv()

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(
    api_key=os.getenv("AI_API_KEY")
)

DEFAULT_MODEL = "claude-3-5-haiku-latest"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMPERATURE = 0.7


async def send_to_llm(messages: list, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    """
    messages — список dict, как в OpenAI, но
    мы должны вытащить "system" отдельно.
    """

    loop = asyncio.get_event_loop()

    # --- Разделяем сообщения Claude-правильно ---
    system_prompt = ""
    normal_messages = []

    for msg in messages:
        if msg["role"] == "system":
            system_prompt += msg["content"] + "\n"
        else:
            normal_messages.append(msg)

    def blocking_call():
        return client.messages.create(
            model=DEFAULT_MODEL,
            system=system_prompt,
            messages=normal_messages,
            max_tokens=max_tokens,
            temperature=DEFAULT_TEMPERATURE
        )

    try:
        res = await loop.run_in_executor(None, blocking_call)
        return res.content[0].text

    except Exception as e:
        logger.error(f"❌ Ошибка Claude: {e}")
        raise