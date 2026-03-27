"""Workbook export for raw and enriched session activity data."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def export_activity_workbook(
    *,
    raw_df: pd.DataFrame,
    activities_df: pd.DataFrame,
    output_path: Path,
) -> Path:
    """Write raw and enriched activity DataFrames to an Excel workbook."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    raw_export = _prepare_for_excel(raw_df)
    enriched_export = _prepare_for_excel(activities_df)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        raw_export.to_excel(writer, index=False, sheet_name="activities_raw_flat")
        enriched_export.to_excel(writer, index=False, sheet_name="activities_enriched")

        workbook = writer.book
        for worksheet in workbook.worksheets:
            worksheet.freeze_panes = "A2"
            for column_cells in worksheet.columns:
                values = ["" if cell.value is None else str(cell.value) for cell in column_cells]
                max_length = min(max(len(value) for value in values), 80) if values else 10
                worksheet.column_dimensions[column_cells[0].column_letter].width = max_length + 2

    return output_path


def _prepare_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    export_df = df.copy()
    for column_name in export_df.columns:
        series = export_df[column_name]
        if pd.api.types.is_datetime64_any_dtype(series):
            export_df[column_name] = series.dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ").fillna("")
            continue
        if pd.api.types.is_bool_dtype(series):
            export_df[column_name] = series.fillna(False)
            continue
        if pd.api.types.is_integer_dtype(series.dtype) or str(series.dtype) == "Int64":
            export_df[column_name] = series.astype("string").fillna("")
    return export_df