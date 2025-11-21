# index_all_files.py
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Добавляем путь к проекту для импорта vector_store
sys.path.insert(0, str(Path(__file__).parent))

from vector_store import vector_store  # Глобальный экземпляр WeaviateStore
from tools.utils import BASE_FILES_DIR
from tools.file_tool import read_file
from tools.excel_tool import read_excel

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def index_all_files(user_id: str = "default"):
    if not vector_store.is_connected():
        logger.info("🔌 Подключение к векторной БД...")
        if not vector_store.connect():
            logger.error("❌ Не удалось подключиться к векторной БД")
            return

    logger.info(f"🔍 Поиск файлов в директории: {BASE_FILES_DIR}")

    supported_extensions = {'.txt', '.pdf', '.docx', '.xlsx', '.xls', '.md', '.csv', '.log', '.json', '.xml', '.html', '.py'}

    all_files = [
        f for f in BASE_FILES_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in supported_extensions
    ]

    if not all_files:
        logger.warning(f"⚠️ Файлы не найдены в {BASE_FILES_DIR}")
        return

    logger.info(f"📁 Найдено файлов: {len(all_files)}")

    success_count = 0
    error_count = 0

    for filepath in all_files:
        try:
            logger.info(f"📄 Индексация: {filepath.name}")

            if filepath.suffix.lower() in ['.xlsx', '.xls']:
                content = read_excel(filepath.name)
            else:
                content = read_file(filepath)

            if not content or str(content).startswith(("Ошибка", "Файл")):
                logger.warning(f"⚠️ Пропущен {filepath.name}: {str(content)[:100]}")
                error_count += 1
                continue

            result = vector_store.add_document(
                content=content,
                filename=filepath.name,
                filetype=filepath.suffix.lstrip('.'),
                user_id=user_id,
                metadata={"source_path": str(filepath)}
            )

            if result.get("success"):
                logger.info(f"✅ {filepath.name} успешно проиндексирован ({result.get('chunks', 0)} чанков)")
                success_count += 1
            else:
                logger.error(f"❌ Ошибка индексации {filepath.name}: {result.get('message')}")
                error_count += 1

        except Exception as e:
            logger.error(f"❌ Исключение при индексации {filepath.name}: {e}")
            error_count += 1

    logger.info("\n" + "="*50)
    logger.info("📊 СТАТИСТИКА ИНДЕКСАЦИИ")
    logger.info("="*50)
    logger.info(f"✅ Успешно: {success_count}")
    logger.info(f"❌ Ошибки: {error_count}")
    logger.info(f"📁 Всего файлов: {len(all_files)}")
    logger.info("="*50)

    try:
        stats = vector_store.get_stats()
        logger.info(f"\n📊 Векторная БД: {stats}")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось получить статистику: {e}")


if __name__ == "__main__":
    print("\n🚀 МАССОВАЯ ИНДЕКСАЦИЯ ФАЙЛОВ В ВЕКТОРНУЮ БД\n")

    if not vector_store.connect():
        logger.error("❌ Не удалось подключиться к векторной БД")
        logger.error("Убедитесь что OPENAI_API_KEY установлен и Weaviate запущен")
        sys.exit(1)

    logger.info("✅ Векторная БД подключена и готова")

    user_id = sys.argv[1].strip() if len(sys.argv) > 1 else "default"
    logger.info(f"👤 User ID: {user_id}")

    index_all_files(user_id)

    vector_store.disconnect()

    print("\n✨ Индексация завершена!")
    print("Теперь вы можете использовать команду 'найди [запрос]' для поиска по файлам\n")