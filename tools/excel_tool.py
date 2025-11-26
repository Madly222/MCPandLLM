# tools/excel_tool.py
from typing import Optional, List
from openpyxl import load_workbook, Workbook
from agent.memory import memory
from tools.utils import BASE_FILES_DIR


def format_cell_value(value) -> str:
    """Форматирует значение ячейки"""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, int):
        return str(value)
    return str(value).strip()


def read_excel(filename: str) -> str:
    """
    Универсальное чтение Excel для любых таблиц.
    Автоматически определяет заголовки и форматирует данные.
    """
    path = BASE_FILES_DIR / filename
    if not path.exists():
        return f"Файл '{filename}' не найден."

    try:
        wb = load_workbook(path, data_only=True)
        text_parts = []
        text_parts.append(f"=== ФАЙЛ: {filename} ===\n")

        for sheet in wb.worksheets:
            text_parts.append(f"\n--- Лист: {sheet.title} ---\n")

            all_rows = []
            for row in sheet.iter_rows(values_only=True):
                cells = [format_cell_value(cell) for cell in row]
                # Пропускаем полностью пустые строки
                if any(cell for cell in cells):
                    all_rows.append(cells)

            if not all_rows:
                text_parts.append("(пустой лист)\n")
                continue

            # Находим строку заголовков (первая строка с 3+ непустых ячеек)
            headers = None
            header_idx = 0
            for idx, row in enumerate(all_rows):
                non_empty = [c for c in row if c]
                if len(non_empty) >= 3:
                    headers = row
                    header_idx = idx
                    break

            # Если заголовки найдены — форматируем как таблицу
            if headers:
                # Строки до заголовков — информация
                for row in all_rows[:header_idx]:
                    info = " | ".join(c for c in row if c)
                    if info:
                        text_parts.append(f"{info}\n")

                # Заголовки
                header_text = " | ".join(h for h in headers if h)
                text_parts.append(f"\n[Заголовки]: {header_text}\n\n")

                # Данные
                for row in all_rows[header_idx + 1:]:
                    row_text = _format_row_smart(row, headers)
                    if row_text:
                        text_parts.append(f"{row_text}\n")
            else:
                # Нет явных заголовков — выводим как есть
                for row in all_rows:
                    row_text = " | ".join(c for c in row if c)
                    if row_text:
                        text_parts.append(f"{row_text}\n")

        return "".join(text_parts)

    except Exception as e:
        return f"Ошибка при чтении Excel: {e}"


def _format_row_smart(row: list, headers: list) -> str:
    """
    Форматирует строку данных с заголовками.
    Пропускает пустые значения.
    """
    parts = []

    for i, cell in enumerate(row):
        if not cell:
            continue

        # Если есть заголовок — добавляем его
        if i < len(headers) and headers[i]:
            parts.append(f"{headers[i]}={cell}")
        else:
            parts.append(str(cell))

    return " | ".join(parts) if parts else ""


def write_excel(filename: str, sheet_name: str, data: list) -> str:
    path = BASE_FILES_DIR / filename
    if path.exists():
        wb = load_workbook(path)
    else:
        wb = Workbook()
    if sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        ws.delete_rows(1, ws.max_row)
    else:
        ws = wb.create_sheet(sheet_name)
    for row in data:
        ws.append(row)
    wb.save(path)
    return f"Файл '{filename}' успешно обновлён."


def select_excel_file(user_id: str, choice: str) -> Optional[str]:
    matched_files = memory.get_user_files(user_id)
    if not matched_files:
        return "Ошибка: Сначала выполните команду поиска Excel файла."
    try:
        index = int(choice.strip()) - 1
        if 0 <= index < len(matched_files):
            selected_file = matched_files[index]
            memory.clear_user_files(user_id)
            state = memory.get_state(user_id) or {}
            state["awaiting_excel_choice"] = False
            state["awaiting_file_choice"] = False
            memory.set_state(user_id, state)
            return read_excel(selected_file.name)
    except Exception:
        pass
    return "Ошибка: Некорректный выбор файла. Введите номер из списка."