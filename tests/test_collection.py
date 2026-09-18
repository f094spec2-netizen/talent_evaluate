import io
import zipfile

import pytest
from openpyxl import Workbook

from app.agents.collection import collect
from app.parsers import InvalidFile, parse_file, preflight
from app.periods import infer_period


@pytest.mark.parametrize(
    ("filename", "start", "issues"),
    [
        ("DEMO_OFFICER01_weekly_2026-W35_2026-08-24_2026-08-30_v01.html", "2026-08-24", []),
        ("weekly_2026-W35_v01.html", "2026-08-24", []),
        ("weekly_2026-08-31_v01.html", "2026-08-31", ["DATE_MAY_BE_PUBLICATION"]),
        ("weekly_2026-W35_2026-08-31_v01.html", "2026-08-24", ["DATE_WEEK_CONFLICT"]),
        ("weekly_2026-W35_2026-08-17_2026-08-23_v01.html", "2026-08-17", ["DATE_WEEK_CONFLICT"]),
        ("weekly_2026-W53_v01.html", "2026-12-28", []),
        ("monthly_2026-07_v01.html", "2026-07-01", []),
        ("monthly_2026-08-03_v01.html", "2026-08-01", ["DATE_MAY_BE_PUBLICATION"]),
    ],
)
def test_periods(filename, start, issues):
    result = infer_period(filename, [])
    assert result["period_start"] == start
    assert result["issues"] == issues


def test_body_conflict_and_invalid_dates():
    result = infer_period(
        "weekly_2026-W35_2026-08-24_2026-08-30_v01.html",
        [
            {"text": "Reporting period: 2026-08-17 to 2026-08-23"},
        ],
    )
    assert "FILENAME_BODY_PERIOD_CONFLICT" in result["issues"]
    assert "DATE_WEEK_CONFLICT" in result["issues"]
    assert "INVALID_DATE" in infer_period("weekly_2026-02-30_v01.html", [])["issues"]
    assert "INVALID_ISO_WEEK" in infer_period("weekly_2025-W53_v01.html", [])["issues"]


def test_submission_date_does_not_override_labelled_reporting_period():
    result = infer_period(
        "weekly_2026-08-31_v01.html",
        [
            {"text": "Reporting period: 2026-08-24 to 2026-08-30"},
        ],
    )
    assert result["period_start"] == "2026-08-24"
    assert result["issues"] == []


def test_task_dates_are_not_treated_as_report_period():
    assert (
        "PERIOD_MISSING"
        in infer_period(
            "weekly_v01.html",
            [
                {"text": "Task: started 2026-08-24, completed 2026-08-30"},
            ],
        )["issues"]
    )


def test_month_filename_and_body_disagreement():
    result = infer_period(
        "monthly_2026-08_v01.html",
        [
            {"text": "Reporting period: 2026-07-01 to 2026-07-31"},
        ],
    )
    assert "FILENAME_BODY_PERIOD_CONFLICT" in result["issues"]


def test_json_reporting_period_conflict():
    result = collect(
        "weekly_2026-W35_v01.json",
        b'{"period":{"start_date":"2026-08-17","end_date":"2026-08-23"},"tasks":[]}',
    )
    assert "DATE_WEEK_CONFLICT" in result.summary["issues"]


def test_unreadable_labelled_body_does_not_silently_pass():
    result = infer_period("weekly_2026-W35_v01.html", [{"text": "Reporting period: unknown"}])
    assert "BODY_PERIOD_UNREADABLE" in result["issues"]


def test_html_scripts_removed_and_provenance(sample):
    result = collect("weekly_2026-W35_v01.html", sample + b"<script>secret_function()</script>")
    assert result.summary["model_trace_id"] is None
    assert result.summary["evidence_status"] == "unverified_source"
    assert all("secret_function" not in r["text"] for r in result.records)
    assert result.records[0]["locator"].startswith("text_line:")


def test_xlsx_preserves_source_rows_and_does_not_evaluate_formulas():
    stream = io.BytesIO()
    workbook = Workbook()
    workbook.active.append(["Reporting period: 2026-08-24 to 2026-08-30"])
    workbook.active.append(["PERSON01", "=1+1"])
    workbook.save(stream)
    result = collect("weekly_2026-W35_v01.xlsx", stream.getvalue())
    assert "FORMULA_NOT_EVALUATED" in result.summary["issues"]
    assert result.summary["body_period"] == ["2026-08-24", "2026-08-30"]
    assert result.records[1]["locator"] == "sheet:1/row:2"


def test_docx_and_json_and_csv():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Example</w:t></w:r></w:p></w:body></w:document>',
        )
    assert parse_file("test.docx", stream.getvalue())[0][0]["text"] == "Example"
    assert parse_file("test.json", b'[{"person":"PERSON01"}]')[0][0]["locator"] == "json:/0"
    assert parse_file("test.csv", b"project,person\nPROJECT01,PERSON01")[0][1]["locator"] == "row:2"


@pytest.mark.parametrize(
    ("filename", "size", "mime", "code"),
    [
        ("../test.html", 1, None, "INVALID_FILENAME"),
        ("test.exe", 1, None, "FORMAT_NOT_SUPPORTED_YET"),
        ("test.xls", 1, None, "FORMAT_NOT_SUPPORTED_YET"),
        ("test.html", 21_000_000, None, "EMPTY_OR_OVERSIZED_FILE"),
        ("test.html", 0, None, "EMPTY_OR_OVERSIZED_FILE"),
        ("test.html", 1, "application/pdf", "MIME_EXTENSION_MISMATCH"),
    ],
)
def test_preflight(filename, size, mime, code):
    with pytest.raises(InvalidFile, match=code):
        preflight(filename, size, mime, 20_000_000)


def test_corrupt_and_explosive_office_archives():
    with pytest.raises(InvalidFile, match="INVALID_OFFICE_OR_ENCRYPTED"):
        parse_file("file.xlsx", b"invalid")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", b"0" * 40_000_001)
    with pytest.raises(InvalidFile, match="ARCHIVE_EXPANSION_LIMIT"):
        parse_file("file.xlsx", stream.getvalue())
