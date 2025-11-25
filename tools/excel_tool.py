# tools/excel_tool.py
from typing import Optional, List
from openpyxl import load_workbook, Workbook
from agent.memory import memory
from tools.utils import BASE_FILES_DIR


def format_cell_value(value) -> str:
    """
    Форматирует значение ячейки:
    - числа округляет до 2 знаков после запятой
    - None превращает в пустую строку
    - остальное в строку
    """
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, int):
        return str(value)
    return str(value)


def read_excel(filename: str) -> str:
    """
    Читает Excel файл и возвращает его содержимое как один большой текст.
    Формат удобен для понимания LLM и создания одного чанка.
    Числа округляются до 2 знаков после запятой.
    """
    path = BASE_FILES_DIR / filename
    if not path.exists():
        return f"Файл '{filename}' не найден."

    try:
        wb = load_workbook(path, data_only=True)
        text_parts = []
        text_parts.append(f"=== EXCEL ФАЙЛ: {filename} ===\n")

        for sheet in wb.worksheets:
            text_parts.append(f"\n--- Лист: {sheet.title} ---\n")

            for row_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                cells = [format_cell_value(cell) for cell in row]
                # Пропускаем полностью пустые строки
                if any(cell.strip() for cell in cells):
                    row_text = " | ".join(cells)
                    text_parts.append(f"Строка {row_idx}: {row_text}")

        return "\n".join(text_parts)

    except Exception as e:
        return f"Ошибка при чтении Excel: {e}"


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