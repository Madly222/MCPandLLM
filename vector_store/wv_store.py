import os
import logging
import hashlib
from typing import List, Dict, Optional
from datetime import datetime

import weaviate
from weaviate.classes.config import Property, DataType, Configure
from weaviate.classes.query import Filter
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class WeaviateStore:

    def __init__(self, host: str = "localhost", port: int = 8082):
        self.host = host
        self.port = port
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.client: Optional[weaviate.WeaviateClient] = None

    def connect(self) -> bool:
        try:
            logger.info(f"Подключение к Weaviate {self.host}:{self.port}...")

            self.client = weaviate.connect_to_local(
                host=self.host,
                port=self.port,
                grpc_port=50051,
                headers={"X-OpenAI-Api-Key": self.openai_api_key} if self.openai_api_key else None
            )

            if not self.client.is_ready():
                logger.error("Weaviate не готов")
                return False

            logger.info("Подключено к Weaviate")
            self._create_schemas()
            return True

        except Exception as e:
            logger.error(f"Ошибка подключения: {e}")
            self.client = None
            return False

    def is_connected(self) -> bool:
        try:
            return self.client is not None and self.client.is_ready()
        except Exception:
            return False

    def disconnect(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
        logger.info("Отключено от Weaviate")

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
                    Property(name="source_path", data_type=DataType.TEXT),
                    Property(name="chunk_index", data_type=DataType.INT),
                    Property(name="total_chunks", data_type=DataType.INT),
                    Property(name="is_table", data_type=DataType.BOOL),
                    Property(name="summary", data_type=DataType.TEXT),
                    Property(name="structure", data_type=DataType.TEXT),
                    Property(name="row_count", data_type=DataType.INT),
                    Property(name="columns", data_type=DataType.TEXT),
                    Property(name="doc_hash", data_type=DataType.TEXT),
                ]
            },
            {
                "name": "FullDocument",
                "properties": [
                    Property(name="content", data_type=DataType.TEXT),
                    Property(name="filename", data_type=DataType.TEXT),
                    Property(name="filetype", data_type=DataType.TEXT),
                    Property(name="user_id", data_type=DataType.TEXT),
                    Property(name="created_at", data_type=DataType.TEXT),
                    Property(name="is_table", data_type=DataType.BOOL),
                    Property(name="summary", data_type=DataType.TEXT),
                    Property(name="structure", data_type=DataType.TEXT),
                    Property(name="row_count", data_type=DataType.INT),
                    Property(name="columns", data_type=DataType.TEXT),
                    Property(name="doc_hash", data_type=DataType.TEXT),
                    Property(name="char_count", data_type=DataType.INT),
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
            try:
                if not self.client.collections.exists(schema["name"]):
                    self.client.collections.create(
                        name=schema["name"],
                        vectorizer_config=Configure.Vectorizer.text2vec_transformers(),
                        properties=schema["properties"]
                    )
                    logger.info(f"Создана схема {schema['name']}")
            except Exception as e:
                logger.error(f"Ошибка создания схемы {schema['name']}: {e}")

    def _hash_content(self, content: str) -> str:
        return hashlib.md5(content.encode()).hexdigest()

    def document_exists(self, filename: str, user_id: str, doc_hash: str) -> bool:
        if not self.is_connected():
            return False
        try:
            collection = self.client.collections.get("FullDocument")
            response = collection.query.fetch_objects(
                limit=1,
                return_properties=["doc_hash"],
                filters=(
                    Filter.by_property("user_id").equal(user_id) &
                    Filter.by_property("filename").equal(filename)
                )
            )
            if response.objects:
                existing_hash = response.objects[0].properties.get("doc_hash", "")
                return existing_hash == doc_hash
            return False
        except Exception:
            return False

    def add_document(self, content: str, filename: str, filetype: str,
                     user_id: str, metadata: Optional[Dict] = None) -> Dict:
        if not self.is_connected():
            return {"success": False, "message": "Weaviate не подключен"}

        try:
            collection = self.client.collections.get("Document")
            meta = metadata or {}

            props = {
                "content": content,
                "filename": filename,
                "filetype": filetype,
                "user_id": user_id,
                "created_at": datetime.now().isoformat(),
                "source_path": meta.get("source_path", ""),
                "chunk_index": meta.get("chunk_index", 0),
                "total_chunks": meta.get("total_chunks", 1),
                "is_table": meta.get("is_table", False),
                "summary": meta.get("summary", ""),
                "structure": meta.get("structure", ""),
                "row_count": meta.get("row_count", 0),
                "columns": meta.get("columns", ""),
                "doc_hash": meta.get("doc_hash", ""),
            }

            collection.data.insert(props)
            logger.info(f"Добавлен чанк '{filename}' [{meta.get('chunk_index', 0) + 1}/{meta.get('total_chunks', 1)}]")
            return {"success": True, "message": "Чанк добавлен"}

        except Exception as e:
            logger.error(f"Ошибка добавления документа: {e}")
            return {"success": False, "message": str(e)}

    def add_full_document(self, content: str, filename: str, filetype: str,
                          user_id: str, metadata: Optional[Dict] = None) -> Dict:
        if not self.is_connected():
            return {"success": False, "message": "Weaviate не подключен"}

        try:
            collection = self.client.collections.get("FullDocument")
            meta = metadata or {}
            doc_hash = self._hash_content(content)

            if self.document_exists(filename, user_id, doc_hash):
                logger.info(f"Документ '{filename}' уже существует (без изменений)")
                return {"success": True, "message": "Документ без изменений", "skipped": True}

            self._delete_full_document(filename, user_id)

            props = {
                "content": content,
                "filename": filename,
                "filetype": filetype,
                "user_id": user_id,
                "created_at": datetime.now().isoformat(),
                "is_table": meta.get("is_table", False),
                "summary": meta.get("summary", ""),
                "structure": meta.get("structure", ""),
                "row_count": meta.get("row_count", 0),
                "columns": meta.get("columns", ""),
                "doc_hash": doc_hash,
                "char_count": len(content),
            }

            collection.data.insert(props)
            logger.info(f"Добавлен полный документ '{filename}' ({len(content)} символов)")
            return {"success": True, "message": "Полный документ добавлен", "doc_hash": doc_hash}

        except Exception as e:
            logger.error(f"Ошибка добавления полного документа: {e}")
            return {"success": False, "message": str(e)}

    def _delete_full_document(self, filename: str, user_id: str):
        try:
            collection = self.client.collections.get("FullDocument")
            collection.data.delete_many(
                where=(
                    Filter.by_property("user_id").equal(user_id) &
                    Filter.by_property("filename").equal(filename)
                )
            )
        except Exception as e:
            logger.error(f"Ошибка удаления документа: {e}")

    def _delete_chunks(self, filename: str, user_id: str):
        try:
            collection = self.client.collections.get("Document")
            collection.data.delete_many(
                where=(
                    Filter.by_property("user_id").equal(user_id) &
                    Filter.by_property("filename").equal(filename)
                )
            )
        except Exception as e:
            logger.error(f"Ошибка удаления чанков: {e}")

    def get_full_document(self, filename: str, user_id: str) -> Optional[Dict]:
        if not self.is_connected():
            return None

        try:
            collection = self.client.collections.get("FullDocument")
            response = collection.query.fetch_objects(
                limit=1,
                return_properties=["content", "filename", "filetype", "is_table",
                                   "summary", "structure", "row_count", "columns", "char_count"],
                filters=(
                    Filter.by_property("user_id").equal(user_id) &
                    Filter.by_property("filename").equal(filename)
                )
            )

            if response.objects:
                obj = response.objects[0]
                return {
                    "content": obj.properties.get("content", ""),
                    "filename": obj.properties.get("filename", ""),
                    "filetype": obj.properties.get("filetype", ""),
                    "is_table": obj.properties.get("is_table", False),
                    "summary": obj.properties.get("summary", ""),
                    "structure": obj.properties.get("structure", ""),
                    "row_count": obj.properties.get("row_count", 0),
                    "columns": obj.properties.get("columns", ""),
                    "char_count": obj.properties.get("char_count", 0),
                }
            return None

        except Exception as e:
            logger.error(f"Ошибка получения документа: {e}")
            return None

    def get_all_full_documents(self, user_id: str, limit: int = 100) -> List[Dict]:
        if not self.is_connected():
            return []

        try:
            collection = self.client.collections.get("FullDocument")
            response = collection.query.fetch_objects(
                limit=limit,
                return_properties=["filename", "filetype", "is_table", "summary",
                                   "structure", "row_count", "columns", "char_count"],
                filters=Filter.by_property("user_id").equal(user_id)
            )

            return [
                {
                    "filename": obj.properties.get("filename", ""),
                    "filetype": obj.properties.get("filetype", ""),
                    "is_table": obj.properties.get("is_table", False),
                    "summary": obj.properties.get("summary", ""),
                    "structure": obj.properties.get("structure", ""),
                    "row_count": obj.properties.get("row_count", 0),
                    "columns": obj.properties.get("columns", ""),
                    "char_count": obj.properties.get("char_count", 0),
                }
                for obj in response.objects
            ]

        except Exception as e:
            logger.error(f"Ошибка получения документов: {e}")
            return []

    def search_by_filename(self, filename_pattern: str, user_id: str, limit: int = 20) -> List[Dict]:
        if not self.is_connected():
            return []

        try:
            collection = self.client.collections.get("Document")
            response = collection.query.fetch_objects(
                limit=100,
                return_properties=["content", "filename", "filetype", "is_table",
                                   "chunk_index", "total_chunks", "summary", "structure"],
                filters=Filter.by_property("user_id").equal(user_id)
            )

            pattern_lower = filename_pattern.lower()
            results = []

            for obj in response.objects:
                filename = obj.properties.get("filename", "").lower()
                if pattern_lower in filename:
                    results.append({
                        "content": obj.properties.get("content", ""),
                        "filename": obj.properties.get("filename", ""),
                        "filetype": obj.properties.get("filetype", ""),
                        "is_table": obj.properties.get("is_table", False),
                        "chunk_index": obj.properties.get("chunk_index", 0),
                        "total_chunks": obj.properties.get("total_chunks", 1),
                        "summary": obj.properties.get("summary", ""),
                        "structure": obj.properties.get("structure", ""),
                        "score": 1.0
                    })

            return results[:limit]
        except Exception as e:
            logger.error(f"Ошибка поиска по имени: {e}")
            return []

    def search_documents(self, query: str, user_id: str, limit: int = 5, min_score: float = 0.5) -> List[Dict]:
        if not self.is_connected():
            return []

        try:
            collection = self.client.collections.get("Document")
            response = collection.query.near_text(
                query=query,
                limit=limit,
                return_metadata=["distance"],
                return_properties=["content", "filename", "filetype", "is_table",
                                   "chunk_index", "total_chunks", "summary", "structure"],
                filters=Filter.by_property("user_id").equal(user_id)
            )

            results = []
            for obj in response.objects:
                distance = obj.metadata.distance if obj.metadata else 1.0
                score = 1 - distance

                if score < min_score:
                    continue

                results.append({
                    "content": obj.properties.get("content", ""),
                    "filename": obj.properties.get("filename", ""),
                    "filetype": obj.properties.get("filetype", ""),
                    "is_table": obj.properties.get("is_table", False),
                    "chunk_index": obj.properties.get("chunk_index", 0),
                    "total_chunks": obj.properties.get("total_chunks", 1),
                    "summary": obj.properties.get("summary", ""),
                    "structure": obj.properties.get("structure", ""),
                    "score": score
                })

            return results
        except Exception as e:
            logger.error(f"Ошибка поиска документов: {e}")
            return []

    def search_full_documents(self, query: str, user_id: str, limit: int = 5, min_score: float = 0.4) -> List[Dict]:
        if not self.is_connected():
            return []

        try:
            collection = self.client.collections.get("FullDocument")
            response = collection.query.near_text(
                query=query,
                limit=limit,
                return_metadata=["distance"],
                return_properties=["content", "filename", "filetype", "is_table",
                                   "summary", "structure", "row_count", "columns", "char_count"],
                filters=Filter.by_property("user_id").equal(user_id)
            )

            results = []
            for obj in response.objects:
                distance = obj.metadata.distance if obj.metadata else 1.0
                score = 1 - distance

                if score < min_score:
                    continue

                results.append({
                    "content": obj.properties.get("content", ""),
                    "filename": obj.properties.get("filename", ""),
                    "filetype": obj.properties.get("filetype", ""),
                    "is_table": obj.properties.get("is_table", False),
                    "summary": obj.properties.get("summary", ""),
                    "structure": obj.properties.get("structure", ""),
                    "row_count": obj.properties.get("row_count", 0),
                    "columns": obj.properties.get("columns", ""),
                    "char_count": obj.properties.get("char_count", 0),
                    "score": score
                })

            return results
        except Exception as e:
            logger.error(f"Ошибка поиска полных документов: {e}")
            return []

    def add_memory(self, fact: str, category: str, user_id: str, importance: float = 1.0) -> Dict:
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
            logger.info(f"Запомнил факт: {fact}")
            return {"success": True, "message": f"Запомнил: {fact}"}
        except Exception as e:
            logger.error(f"Ошибка добавления памяти: {e}")
            return {"success": False, "message": str(e)}

    def search_memory(self, query: str, user_id: str, limit: int = 3) -> List[str]:
        if not self.is_connected():
            return []

        try:
            collection = self.client.collections.get("UserMemory")
            response = collection.query.near_text(
                query,
                limit=limit,
                return_properties=["fact"],
                filters=Filter.by_property("user_id").equal(user_id)
            )
            return [obj.properties["fact"] for obj in response.objects]
        except Exception:
            return []

    def add_chat_message(self, message: str, role: str, user_id: str):
        if not self.is_connected() or len(message.strip()) < 1:
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
            logger.error(f"Ошибка добавления сообщения: {e}")

    def search_chat_history(self, query: str, user_id: str, limit: int = 5) -> List[Dict]:
        if not self.is_connected():
            return []

        try:
            collection = self.client.collections.get("ChatHistory")
            response = collection.query.near_text(
                query,
                limit=limit,
                return_properties=["message", "role", "timestamp"],
                filters=Filter.by_property("user_id").equal(user_id)
            )
            return [
                {
                    "message": obj.properties["message"],
                    "role": obj.properties["role"],
                    "timestamp": obj.properties["timestamp"]
                }
                for obj in response.objects
            ]
        except Exception:
            return []

    def get_stats(self) -> Dict:
        if not self.is_connected():
            return {"documents": 0, "full_documents": 0, "memories": 0, "chat_messages": 0}

        stats = {}
        try:
            for name in ["Document", "FullDocument", "UserMemory", "ChatHistory"]:
                collection = self.client.collections.get(name)
                agg = collection.aggregate.over_all(total_count=True)
                stats[name.lower()] = agg.total_count
        except Exception as e:
            logger.error(f"Ошибка статистики: {e}")

        return {
            "documents": stats.get("document", 0),
            "full_documents": stats.get("fulldocument", 0),
            "memories": stats.get("usermemory", 0),
            "chat_messages": stats.get("chathistory", 0)
        }

    def get_all_user_documents(self, user_id: str, limit: int = 100) -> List[Dict]:
        if not self.is_connected():
            return []

        try:
            collection = self.client.collections.get("Document")
            response = collection.query.fetch_objects(
                limit=limit,
                return_properties=["filename", "is_table"],
                filters=Filter.by_property("user_id").equal(user_id)
            )
            return [{"filename": obj.properties.get("filename", "")} for obj in response.objects]
        except Exception:
            return []

    def clear_user_data(self, user_id: str):
        if not self.is_connected():
            return

        try:
            for name in ["Document", "FullDocument", "UserMemory", "ChatHistory"]:
                collection = self.client.collections.get(name)
                collection.data.delete_many(
                    where=Filter.by_property("user_id").equal(user_id)
                )
            logger.info(f"Данные пользователя {user_id} удалены")
        except Exception as e:
            logger.error(f"Ошибка очистки данных: {e}")


vector_store = WeaviateStore()

if __name__ == "__main__":
    if vector_store.connect():
        print("WeaviateStore подключен")
        stats = vector_store.get_stats()
        print(f"Статистика: {stats}")
        vector_store.disconnect()
    else:
        print("Ошибка подключения")