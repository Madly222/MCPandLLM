"""
Vector Store пакет с абстракцией для легкой замены векторных БД
"""

from vector_store.interface import VectorStoreInterface
from vector_store.weaviate_store import WeaviateStore, vector_store

__all__ = ['VectorStoreInterface', 'WeaviateStore', 'vector_store']