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
DEFAULT_MODEL = "mistralai/mistral-7b-instruct:free"
DEFAULT_MAX_TOKENS = 800  # ✅ Уменьшили с 2048
DEFAULT_TEMPERATURE = 0.7
MIN_MAX_TOKENS = 400  # Минимум для fallback


def estimate_tokens(text: str) -> int:
    """Примерная оценка токенов"""
    return len(text) // 3


async def send_to_llm(messages: list, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    """Отправка запроса к LLM через OpenRouter с полным логированием"""

    # ✅ Логируем размер промпта
    total_chars = sum(len(msg.get("content", "")) for msg in messages)
    estimated_input_tokens = estimate_tokens(str(messages))
    logger.info(f"📊 Размер промпта: {total_chars} символов (~{estimated_input_tokens} токенов)")
    logger.info(f"🎯 Запрашиваем max_tokens: {max_tokens}")

    loop = asyncio.get_event_loop()

    def blocking_call(tokens_limit):
        return client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=messages,
            max_tokens=tokens_limit,
            temperature=DEFAULT_TEMPERATURE
        )

    try:
        # Первая попытка
        logger.info("📡 Отправка запроса к LLM...")
        res = await loop.run_in_executor(None, lambda: blocking_call(max_tokens))

        # ✅ Проверяем ответ
        if not res or not res.choices:
            logger.error("❌ LLM не вернул choices")
            return "Извините, модель не вернула ответ."

        response_content = res.choices[0].message.content

        # ✅ Логируем результат
        if response_content:
            logger.info(f"✅ LLM ответил: {len(response_content)} символов")
            logger.debug(f"Первые 200 символов: {response_content[:200]}...")
        else:
            logger.error("❌ LLM вернул пустой content!")
            return "Извините, получен пустой ответ от модели."

        return response_content

    except Exception as e:
        error_str = str(e)
        logger.error(f"❌ Ошибка LLM (полная): {e}")

        # ✅ Обработка ошибки 402 (недостаточно кредитов)
        if "402" in error_str or "afford" in error_str.lower():
            logger.warning(f"⚠️ Ошибка 402: недостаточно кредитов для {max_tokens} токенов")

            # Пытаемся с минимальным лимитом
            if max_tokens > MIN_MAX_TOKENS:
                logger.info(f"🔄 Повторная попытка с max_tokens={MIN_MAX_TOKENS}")
                try:
                    res = await loop.run_in_executor(None, lambda: blocking_call(MIN_MAX_TOKENS))
                    response_content = res.choices[0].message.content

                    if response_content:
                        logger.info(f"✅ Успешно получен ответ со второй попытки")
                        return response_content
                    else:
                        return "Извините, получен пустой ответ."

                except Exception as e2:
                    logger.error(f"❌ Ошибка даже с минимальным max_tokens: {e2}")
                    return "Недостаточно кредитов OpenRouter. Пополните баланс: https://openrouter.ai/settings/credits"
            else:
                return "Недостаточно кредитов OpenRouter. Пополните баланс: https://openrouter.ai/settings/credits"

        # ✅ Обработка других ошибок
        logger.error(f"❌ Критическая ошибка LLM: {e}", exc_info=True)
        return f"Ошибка при обращении к модели: {str(e)}"