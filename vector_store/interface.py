"""
Абстрактный интерфейс для векторных БД.
Позволяет легко менять Weaviate на Milvus, Elasticsearch и т.д.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from datetime import datetime


class VectorStoreInterface(ABC):
    """Базовый интерфейс для всех векторных хранилищ"""

    @abstractmethod
    def connect(self) -> bool:
        """
        Подключение к векторному хранилищу

        Returns:
            bool: True если подключение успешно
        """
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """
        Проверка активного подключения

        Returns:
            bool: True если подключено
        """
        pass

    @abstractmethod
    def disconnect(self):
        """Отключение от хранилища"""
        pass

    # === Работа с документами ===

    @abstractmethod
    def add_document(self, content: str, filename: str, filetype: str,
                     user_id: str, metadata: Optional[Dict] = None) -> Dict:
        """
        Добавление документа с векторизацией

        Args:
            content: Содержимое документа
            filename: Имя файла
            filetype: Тип файла (txt, pdf, docx, xlsx)
            user_id: ID пользователя
            metadata: Дополнительные метаданные

        Returns:
            Dict с результатом: {"success": bool, "message": str, "chunks": int}
        """
        pass

    @abstractmethod
    def search_documents(self, query: str, user_id: str,
                         limit: int = 5) -> List[Dict]:
        """
        Семантический поиск по документам

        Args:
            query: Поисковый запрос
            user_id: ID пользователя
            limit: Количество результатов

        Returns:
            List[Dict]: [{"content": str, "filename": str, "filetype": str, "score": float}]
        """
        pass

    # === Работа с памятью пользователя ===

    @abstractmethod
    def add_memory(self, fact: str, category: str, user_id: str,
                   importance: float = 1.0) -> Dict:
        """
        Добавление факта в долговременную память

        Args:
            fact: Факт о пользователе
            category: Категория (preference, personal, work, etc.)
            user_id: ID пользователя
            importance: Важность (0-1)

        Returns:
            Dict: {"success": bool, "message": str}
        """
        pass

    @abstractmethod
    def search_memory(self, query: str, user_id: str,
                      limit: int = 3) -> List[str]:
        """
        Поиск фактов в памяти пользователя

        Args:
            query: Поисковый запрос
            user_id: ID пользователя
            limit: Количество результатов

        Returns:
            List[str]: Список релевантных фактов
        """
        pass

    # === Работа с историей чатов ===

    @abstractmethod
    def add_chat_message(self, message: str, role: str, user_id: str):
        """
        Сохранение сообщения чата

        Args:
            message: Текст сообщения
            role: Роль (user/assistant)
            user_id: ID пользователя
        """
        pass

    @abstractmethod
    def search_chat_history(self, query: str, user_id: str,
                            limit: int = 5) -> List[Dict]:
        """
        Поиск в истории чатов

        Args:
            query: Поисковый запрос
            user_id: ID пользователя
            limit: Количество результатов

        Returns:
            List[Dict]: [{"message": str, "role": str, "timestamp": str}]
        """
        pass

    # === Утилиты ===

    @abstractmethod
    def get_stats(self) -> Dict:
        """
        Получение статистики хранилища

        Returns:
            Dict: {"documents": int, "memories": int, "chat_messages": int}
        """
        pass

    @abstractmethod
    def clear_user_data(self, user_id: str):
        """
        Очистка всех данных пользователя

        Args:
            user_id: ID пользователя
        """
        pass