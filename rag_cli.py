# rag_cli.py

import argparse
from pathlib import Path
from tools.chunking_tool import index_file, index_all_files
from tools.search_tool import search_documents
from vector_store import vector_store

def main():
    parser = argparse.ArgumentParser(description="CLI для работы с RAG и Weaviate")
    parser.add_argument("--connect", action="store_true", help="Подключиться к Weaviate")
    parser.add_argument("--index", type=str, help="Индексировать один файл")
    parser.add_argument("--reindex", action="store_true", help="Переиндексация всех файлов")
    parser.add_argument("--search", type=str, help="Семантический поиск")
    parser.add_argument("--user", type=str, default="default_user", help="ID пользователя")
    args = parser.parse_args()

    user_id = args.user

    # Подключение к Weaviate
    if args.connect:
        if vector_store.connect():
            print("✅ Подключение к Weaviate успешно")
        else:
            print("❌ Ошибка подключения к Weaviate")
            return

    # Индексация одного файла
    if args.index:
        file_path = Path(args.index)
        index_file(file_path, user_id=user_id)

    # Переиндексация всех файлов
    if args.reindex:
        index_all_files(user_id=user_id)

    # Поиск по ключевому слову
    if args.search:
        results = search_documents(args.search, user_id=user_id)
        if results:
            print(f"🔍 Результаты поиска для '{args.search}':")
            for r in results:
                snippet = r.get("content", "")[:200].replace("\n", " ")
                print(f"- {r.get('filename', 'unknown')}: {snippet}...")
        else:
            print(f"❌ Ничего не найдено для запроса '{args.search}'")

    vector_store.disconnect()

if __name__ == "__main__":
    main()