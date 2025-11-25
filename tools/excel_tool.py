# tools/excel_tool.py
from typing import Optional, List
from openpyxl import load_workbook, Workbook
from agent.memory import memory
from tools.utils import BASE_FILES_DIR

def read_excel(filename: str) -> List[str]:
    """
    Возвращает список всех строк Excel файла (все листы),
    каждая строка — это текст всех ячеек через пробел.
    """
    path = BASE_FILES_DIR / filename
    if not path.exists():
        return [f"Файл '{filename}' не найден."]

    try:
        wb = load_workbook(path, data_only=True)
        all_rows = []

        for sheet in wb.worksheets:
            for row in sheet.iter_rows(values_only=True):
                # Преобразуем все ячейки в строку
                row_text = " ".join(str(cell) if cell is not None else "" for cell in row)
                all_rows.append(row_text)

        return all_rows

    except Exception as e:
        return [f"Ошибка при чтении Excel: {e}"]

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

def select_excel_file(user_id: str, choice: str) -> Optional[List[dict]]:
    matched_files = memory.get_user_files(user_id)
    if not matched_files:
        return [ {"error": "Сначала выполните команду поиска Excel файла."} ]
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
    return [ {"error": "Некорректный выбор файла. Введите номер из списка."} ]