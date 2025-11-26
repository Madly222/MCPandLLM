import os
import asyncio
import logging
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
logger = logging.getLogger(__name__)

# === Настройки ===
DEFAULT_MODEL = "mistralai/mistral-7b-instruct:free"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMPERATURE = 0.7

# Создаём клиент OpenRouter
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("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")
)

async def send_to_llm(messages: list, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    """Отправка запроса к Mistral-7B через OpenRouter"""

    loop = asyncio.get_event_loop()

    def blocking_call():
        return client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            temperature=DEFAULT_TEMPERATURE,
            extra_headers={
                # Опционально: для рейтинга на openrouter.ai
                "HTTP-Referer": os.getenv("YOUR_SITE_URL", ""),
                "X-Title": os.getenv("YOUR_SITE_NAME", "")
            },
            extra_body={}
        )

    try:
        res = await loop.run_in_executor(None, blocking_call)
        return res.choices[0].message.content
    except Exception as e:
        logger.error(f"❌ Ошибка LLM: {e}")
        raise

# === Пример использования ===
async def main():
    messages = [{"role": "user", "content": "What is the meaning of life?"}]
    response = await send_to_llm(messages)
    print(response)

if __name__ == "__main__":
    asyncio.run(main())