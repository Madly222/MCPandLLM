import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
import re
from difflib import SequenceMatcher

from tools.template_analyzer import TemplateSchema, ColumnSchema, COLUMN_ALIASES
from tools.file_reader_tool import ExtractedContent, ExtractedTable

logger = logging.getLogger(__name__)


@dataclass
class ColumnMapping:
    template_column: ColumnSchema
    source_column: Optional[str] = None
    source_index: Optional[int] = None
    confidence: float = 0.0
    transform: Optional[str] = None


@dataclass
class DataMapping:
    template: TemplateSchema
    source: ExtractedContent
    column_mappings: List[ColumnMapping] = field(default_factory=list)
    unmapped_template_columns: List[str] = field(default_factory=list)
    unmapped_source_columns: List[str] = field(default_factory=list)

    def get_mapping_for_template_column(self, col_name: str) -> Optional[ColumnMapping]:
        for m in self.column_mappings:
            if m.template_column.name.lower() == col_name.lower():
                return m
        return None

    def get_mapped_value(self, template_col: str, source_row: List[Any]) -> Any:
        mapping = self.get_mapping_for_template_column(template_col)
        if mapping and mapping.source_index is not None:
            if mapping.source_index < len(source_row):
                return source_row[mapping.source_index]
        return None


def _normalize_name(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+', ' ', name)
    return name


def _get_all_aliases(name: str) -> set:
    aliases = {_normalize_name(name)}
    name_lower = name.lower().strip()

    for base, alias_list in COLUMN_ALIASES.items():
        if name_lower == base or name_lower in alias_list:
            aliases.add(base)
            aliases.update(alias_list)
            break

        for alias in alias_list:
            if alias in name_lower or name_lower in alias:
                aliases.add(base)
                aliases.update(alias_list)
                break

    return aliases


def _calculate_similarity(name1: str, name2: str) -> float:
    n1 = _normalize_name(name1)
    n2 = _normalize_name(name2)

    if n1 == n2:
        return 1.0

    aliases1 = _get_all_aliases(name1)
    aliases2 = _get_all_aliases(name2)

    if aliases1 & aliases2:
        return 0.95

    ratio = SequenceMatcher(None, n1, n2).ratio()

    if n1 in n2 or n2 in n1:
        ratio = max(ratio, 0.8)

    return ratio


def _find_best_match(
        template_col: ColumnSchema,
        source_headers: List[str],
        used_indices: set
) -> Tuple[Optional[int], float]:
    best_idx = None
    best_score = 0.0

    for idx, header in enumerate(source_headers):
        if idx in used_indices:
            continue

        score = _calculate_similarity(template_col.name, header)

        if score > best_score:
            best_score = score
            best_idx = idx

    return best_idx, best_score


def map_columns(
        template: TemplateSchema,
        source: ExtractedContent,
        min_confidence: float = 0.5
) -> DataMapping:
    mapping = DataMapping(
        template=template,
        source=source
    )

    if not source.tables:
        logger.warning(f"No tables in source: {source.filename}")
        return mapping

    source_table = source.tables[0]
    source_headers = source_table.headers

    used_source_indices = set()

    for template_col in template.columns:
        best_idx, confidence = _find_best_match(
            template_col,
            source_headers,
            used_source_indices
        )

        if best_idx is not None and confidence >= min_confidence:
            col_mapping = ColumnMapping(
                template_column=template_col,
                source_column=source_headers[best_idx],
                source_index=best_idx,
                confidence=confidence
            )
            mapping.column_mappings.append(col_mapping)
            used_source_indices.add(best_idx)
        else:
            col_mapping = ColumnMapping(
                template_column=template_col,
                confidence=0.0
            )
            mapping.column_mappings.append(col_mapping)
            mapping.unmapped_template_columns.append(template_col.name)

    for idx, header in enumerate(source_headers):
        if idx not in used_source_indices:
            mapping.unmapped_source_columns.append(header)

    return mapping


def map_multiple_sources(
        template: TemplateSchema,
        sources: List[ExtractedContent],
        min_confidence: float = 0.5
) -> List[DataMapping]:
    mappings = []
    for source in sources:
        mapping = map_columns(template, source, min_confidence)
        mappings.append(mapping)
    return mappings


def extract_mapped_data(
        mapping: DataMapping,
        max_rows: Optional[int] = None
) -> List[Dict[str, Any]]:
    if not mapping.source.tables:
        return []

    source_table = mapping.source.tables[0]
    rows = source_table.rows

    if max_rows:
        rows = rows[:max_rows]

    result = []

    for row_data in rows:
        mapped_row = {}

        for col_mapping in mapping.column_mappings:
            template_col = col_mapping.template_column.name

            if col_mapping.source_index is not None and col_mapping.source_index < len(row_data):
                value = row_data[col_mapping.source_index]
                mapped_row[template_col] = value
            else:
                mapped_row[template_col] = None

        if any(v is not None and str(v).strip() for v in mapped_row.values()):
            result.append(mapped_row)

    return result


def generate_mapping_report(mappings: List[DataMapping]) -> str:
    lines = ["ОТЧЁТ О МАППИНГЕ ДАННЫХ", "=" * 60, ""]

    for mapping in mappings:
        lines.append(f"Источник: {mapping.source.filename}")
        lines.append("-" * 40)

        lines.append("Сопоставленные колонки:")
        for col_map in mapping.column_mappings:
            if col_map.source_column:
                conf_str = f"{col_map.confidence:.0%}"
                lines.append(
                    f"  {col_map.template_column.name} <- {col_map.source_column} [{conf_str}]"
                )

        if mapping.unmapped_template_columns:
            lines.append("")
            lines.append("Не найдены в источнике:")
            for col in mapping.unmapped_template_columns:
                lines.append(f"  - {col}")

        if mapping.unmapped_source_columns:
            lines.append("")
            lines.append("Не использованы из источника:")
            for col in mapping.unmapped_source_columns:
                lines.append(f"  - {col}")

        lines.append("")

    return "\n".join(lines)


def format_mapping_for_llm(
        template: TemplateSchema,
        mappings: List[DataMapping]
) -> str:
    lines = [
        "ЗАДАЧА: Создать файл по структуре шаблона",
        "",
        "ШАБЛОН:",
        f"  Файл: {template.filename}",
        f"  Колонки: {', '.join(template.get_column_names())}",
        ""
    ]

    lines.append("ИСТОЧНИКИ ДАННЫХ:")

    all_data = []

    for mapping in mappings:
        lines.append(f"\n  {mapping.source.filename}:")

        mapped_cols = []
        for cm in mapping.column_mappings:
            if cm.source_column:
                mapped_cols.append(f"{cm.template_column.name}={cm.source_column}")

        if mapped_cols:
            lines.append(f"    Маппинг: {', '.join(mapped_cols)}")

        data = extract_mapped_data(mapping)
        if data:
            lines.append(f"    Строк данных: {len(data)}")
            all_data.extend(data)

    lines.append("")
    lines.append("ИЗВЛЕЧЁННЫЕ ДАННЫЕ:")
    lines.append("-" * 60)

    if all_data:
        headers = template.get_column_names()
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        for row in all_data[:50]:
            values = [str(row.get(h, ""))[:30] for h in headers]
            lines.append("| " + " | ".join(values) + " |")

        if len(all_data) > 50:
            lines.append(f"... ещё {len(all_data) - 50} строк")

    lines.append("")
    lines.append("ФОРМАТ ОТВЕТА (JSON):")
    lines.append("```json")
    lines.append("{")
    lines.append('  "title": "Название документа",')
    lines.append('  "sheets": [')
    lines.append('    {')
    lines.append('      "name": "Лист1",')
    lines.append(f'      "headers": {template.get_column_names()},')
    lines.append('      "rows": [')
    lines.append('        ["значение1", "значение2", ...],')
    lines.append('        ...')
    lines.append('      ]')
    lines.append('    }')
    lines.append('  ]')
    lines.append("}")
    lines.append("```")

    return "\n".join(lines)