import os
import logging
from typing import List, Dict, Optional
from datetime import datetime

import weaviate
from weaviate.classes.config import Property, DataType, Configure
from dotenv import load_dotenv

load_dotenv()  # Загружаем ключи из .env

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class WeaviateStore:

    def __init__(self, url: str = "http://localhost:8082"):
        self.url = url
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.client: Optional[weaviate.WeaviateClient] = None

    # ------------------- Подключение -------------------
    def connect(self) -> bool:
        """Подключение к Weaviate через HTTP"""
        try:
            logger.info(f"🔌 Подключение к Weaviate на {self.url}...")
            self.client = weaviate.WeaviateClient(url=self.url)
            if not self.client.is_ready():
                logger.error("❌ Weaviate не готов!")
                return False
            logger.info("✅ Подключено к Weaviate")
            self._create_schemas()
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка подключения: {e}")
            self.client = None
            return False

    def is_connected(self) -> bool:
        return self.client is not None and self.client.is_ready()

    def disconnect(self):
        self.client = None
        logger.info("🔌 Отключено от Weaviate")

    # ------------------- Создание схем -------------------
    def _create_schemas(self):
        if not self.is_connected():
            return

        schemas = [
            {
                "name": "Document",
                "properties": [
                    Property(name="content", data_type=DataType.TEXT),
                    Property(name="filename", data_type=DataType.TEXT),
                    Property(name="filetype", data_type=DataType.TEXT),
                    Property(name="user_id", data_type=DataType.TEXT),
                    Property(name="created_at", data_type=DataType.TEXT),
                ]
            },
            {
                "name": "ChatHistory",
                "properties": [
                    Property(name="message", data_type=DataType.TEXT),
                    Property(name="role", data_type=DataType.TEXT),
                    Property(name="user_id", data_type=DataType.TEXT),
                    Property(name="timestamp", data_type=DataType.TEXT),
                ]
            },
            {
                "name": "UserMemory",
                "properties": [
                    Property(name="fact", data_type=DataType.TEXT),
                    Property(name="category", data_type=DataType.TEXT),
                    Property(name="user_id", data_type=DataType.TEXT),
                    Property(name="importance", data_type=DataType.NUMBER),
                    Property(name="created_at", data_type=DataType.TEXT),
                ]
            }
        ]

        for schema in schemas:
            if not self.client.collections.exists(schema["name"]):
                self.client.collections.create(
                    name=schema["name"],
                    vectorizer_config=Configure.Vectorizer.text2vec_openai(
                        model="text-embedding-3-small"
                    ) if self.openai_api_key else None,
                    properties=schema["properties"]
                )
                logger.info(f"✅ Создана схема {schema['name']}")

    # ------------------- Работа с документами -------------------
    def add_document(self, content: str, filename: str, filetype: str,
                     user_id: str, metadata: Optional[Dict] = None) -> Dict:
        if not self.is_connected():
            return {"success": False, "message": "Weaviate не подключен", "chunks": 0}

        try:
            collection = self.client.collections.get("Document")
            chunks = self._split_into_chunks(content)
            added = 0

            for chunk in chunks:
                collection.data.insert({
                    "content": chunk,
                    "filename": filename,
                    "filetype": filetype,
                    "user_id": user_id,
                    "created_at": datetime.now().isoformat(),
                    **(metadata or {})
                })
                added += 1

            logger.info(f"✅ Добавлено {added} чанков из '{filename}'")
            return {"success": True, "message": f"{filename} проиндексирован ({added} частей)", "chunks": added}
        except Exception as e:
            logger.error(f"❌ Ошибка добавления документа: {e}")
            return {"success": False, "message": str(e), "chunks": 0}

    def search_documents(self, query: str, user_id: str, limit: int = 5) -> List[Dict]:
        if not self.is_connected():
            return []

        try:
            collection = self.client.collections.get("Document")
            response = collection.query.near_text(
                query=query,
                limit=limit,
                return_properties=["content", "filename", "filetype"],
                filters=collection.filter.by_property("user_id").equal(user_id)
            )

            return [
                {"content": obj.properties["content"],
                 "filename": obj.properties["filename"],
                 "filetype": obj.properties["filetype"],
                 "score": 1.0}
                for obj in response.objects
            ]
        except Exception as e:
            logger.error(f"❌ Ошибка поиска документов: {e}")
            return []

    # ------------------- Работа с памятью -------------------
    def add_memory(self, fact: str, category: str, user_id: str,
                   importance: float = 1.0) -> Dict:
        if not self.is_connected():
            return {"success": False, "message": "Weaviate не подключен"}

        try:
            collection = self.client.collections.get("UserMemory")
            collection.data.insert({
                "fact": fact,
                "category": category,
                "user_id": user_id,
                "importance": importance,
                "created_at": datetime.now().isoformat()
            })
            logger.info(f"✅ Запомнил факт: {fact}")
            return {"success": True, "message": f"Запомнил: {fact}"}
        except Exception as e:
            logger.error(f"❌ Ошибка добавления памяти: {e}")
            return {"success": False, "message": str(e)}

    def search_memory(self, query: str, user_id: str, limit: int = 3) -> List[str]:
        if not self.is_connected():
            return []

        try:
            collection = self.client.collections.get("UserMemory")
            response = collection.query.near_text(
                query=query,
                limit=limit,
                return_properties=["fact"],
                filters=collection.filter.by_property("user_id").equal(user_id)
            )
            return [obj.properties["fact"] for obj in response.objects]
        except Exception as e:
            logger.error(f"❌ Ошибка поиска памяти: {e}")
            return []

    # ------------------- Работа с чатом -------------------
    def add_chat_message(self, message: str, role: str, user_id: str):
        if not self.is_connected() or len(message.strip()) < 10:
            return

        try:
            collection = self.client.collections.get("ChatHistory")
            collection.data.insert({
                "message": message,
                "role": role,
                "user_id": user_id,
                "timestamp": datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"❌ Ошибка добавления сообщения: {e}")

    def search_chat_history(self, query: str, user_id: str, limit: int = 5) -> List[Dict]:
        if not self.is_connected():
            return []

        try:
            collection = self.client.collections.get("ChatHistory")
            response = collection.query.near_text(
                query=query,
                limit=limit,
                return_properties=["message", "role", "timestamp"],
                filters=collection.filter.by_property("user_id").equal(user_id)
            )
            return [
                {"message": obj.properties["message"],
                 "role": obj.properties["role"],
                 "timestamp": obj.properties["timestamp"]}
                for obj in response.objects
            ]
        except Exception as e:
            logger.error(f"❌ Ошибка поиска истории: {e}")
            return []

    # ------------------- Утилиты -------------------
    def get_stats(self) -> Dict:
        if not self.is_connected():
            return {"documents": 0, "memories": 0, "chat_messages": 0}

        stats = {}
        try:
            for name in ["Document", "UserMemory", "ChatHistory"]:
                collection = self.client.collections.get(name)
                agg = collection.aggregate.over_all(total_count=True)
                stats[name.lower()] = agg.total_count
        except Exception as e:
            logger.error(f"❌ Ошибка статистики: {e}")

        return {
            "documents": stats.get("document", 0),
            "memories": stats.get("usermemory", 0),
            "chat_messages": stats.get("chathistory", 0)
        }

    def clear_user_data(self, user_id: str):
        if not self.is_connected():
            return

        try:
            for name in ["Document", "UserMemory", "ChatHistory"]:
                collection = self.client.collections.get(name)
                collection.data.delete_many(
                    where=collection.filter.by_property("user_id").equal(user_id)
                )
            logger.info(f"✅ Данные пользователя {user_id} удалены")
        except Exception as e:
            logger.error(f"❌ Ошибка очистки данных: {e}")

# ------------------- Вспомогательные методы -------------------
@staticmethod
def _split_into_chunks(text: str, max_words: int = 500) -> List[str]:
    words = text.split()
    return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]

# ------------------- Глобальный экземпляр -------------------

vector_store = WeaviateStore()

if __name__ == "__main__":
    if vector_store.connect():
        print("WeaviateStore подключен и готов к работе!")
    else:
        print("Ошибка подключения к WeaviateStore")

