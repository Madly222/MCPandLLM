import os
from dotenv import load_dotenv
import anthropic
import asyncio
import logging

load_dotenv()

logger = logging.getLogger(__name__)

# === КЛИЕНТ ANTHROPIC ===
client = anthropic.Anthropic(
    api_key=os.getenv("AI_API_KEY")
)

# === НАСТРОЙКИ ===
DEFAULT_MODEL = "claude-3-5-haiku-latest"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMPERATURE = 0.7


async def send_to_llm(messages: list, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    """
    Отправка запроса к Claude 3.5 Haiku.
    messages — список вида [{"role": "user", "content": "текст"}]
    """

    loop = asyncio.get_event_loop()

    def blocking_call():
        return client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=max_tokens,
            temperature=DEFAULT_TEMPERATURE,
            messages=messages
        )

    try:
        res = await loop.run_in_executor(None, blocking_call)

        # В new API контент — это массив блоков
        return res.content[0].text

    except Exception as e:
        logger.error(f"❌ Ошибка Claude: {e}")
        raise