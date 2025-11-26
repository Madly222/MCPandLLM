import os
from dotenv import load_dotenv
from openai import OpenAI
import asyncio
import logging

load_dotenv()

logger = logging.getLogger(__name__)

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

# === НАСТРОЙКИ ===
DEFAULT_MODEL = "deepseek/deepseek-r1:free"
DEFAULT_MAX_TOKENS = 2048  # Лимит на ответ
DEFAULT_TEMPERATURE = 0.7


async def send_to_llm(messages: list, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    """Отправка запроса к LLM через OpenRouter"""

    loop = asyncio.get_event_loop()

    def blocking_call():
        return client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=messages,
            max_tokens=max_tokens,  # ✅ Добавлено!
            temperature=DEFAULT_TEMPERATURE
        )

    try:
        res = await loop.run_in_executor(None, blocking_call)
        return res.choices[0].message.content
    except Exception as e:
        logger.error(f"❌ Ошибка LLM: {e}")
        raise