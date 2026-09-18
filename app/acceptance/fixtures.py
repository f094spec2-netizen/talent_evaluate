"""PUBLIC SYNTHETIC fixtures only. Gold is written independently, never from Agent output."""

import base64
import copy
import io
import json
import re
import zipfile
from datetime import datetime

from openpyxl import Workbook
from sqlalchemy import select

from app.acceptance.service import add_answer, digest
from app.database import AcceptanceCase

PERIOD = "Reporting period: 2026-08-24 to 2026-08-30"
TEXT = "PROJECT_001 delivered by PERSON_001; acceptance pending"
STEM = "ORG01_OFF01_周报_2026-W35_2026-08-24_2026-08-30_v01"


def stable_zip(content):
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(content)) as source,
        zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for name in sorted(source.namelist()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            payload = source.read(name)
            if name == "docProps/core.xml":
                payload = re.sub(
                    rb"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", b"2026-01-01T00:00:00Z", payload
                )
            target.writestr(info, payload)
    return output.getvalue()


def content_for(ext, period=PERIOD, text=TEXT):
    if ext in ("html", "htm"):
        return f"<html><body><p>{period}</p><p>{text}</p></body></html>".encode()
    if ext == "csv":
        return f"{period}\n{text}\n".encode("utf-8-sig")
    if ext == "json":
        return json.dumps(
            {
                "reporting_period": {"start_date": "2026-08-24", "end_date": "2026-08-30"},
                "event": text,
            }
        ).encode()
    if ext in ("xlsx", "xlsm"):
        book = Workbook()
        book.properties.created = book.properties.modified = datetime(2026, 1, 1)
        book.active.append([period])
        book.active.append([text])
        data = io.BytesIO()
        book.save(data)
        book.close()
        return stable_zip(data.getvalue())
    if ext == "docx":
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
            )
            archive.writestr(
                "word/document.xml",
                f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{period}</w:t></w:r></w:p><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>',
            )
        return stable_zip(stream.getvalue())
    raise ValueError("UNSUPPORTED_FIXTURE_FORMAT")


def file(filename=STEM + ".html", content=None, mime=None):
    return {
        "filename": filename,
        "content_base64": base64.b64encode(
            content if content is not None else content_for("html")
        ).decode(),
        "mime": mime,
    }


def check(path, value, op="eq", critical=True):
    return {"path": path, "op": op, "value": value, "critical": critical}


def answer(
    checks,
    human=False,
    evidence=None,
    basis="合成材料明列工作期間、版本及未核驗交付；依上傳規則判定，不採用 Agent 輸出作答案。",
):
    return {
        "expected_human": human,
        "checks": [
            check("disposition", "human" if human else "automatic", critical=human),
            *checks,
        ],
        "evidence": evidence or [],
        "basis": basis,
        "rubric": [],
    }


def candidate(key, agent, track, title, task, gold, index):
    # Independent synthetic source namespaces: format variations inside a case stay together,
    # while a shared demo document must not become both development and held-out evidence.
    task = copy.deepcopy(task)
    replacements = {
        "PROJECT_001": "PROJECT_" + key.replace("-", "_"),
        "PERSON_001": "PERSON_" + key.replace("-", "_"),
    }

    def replace_bytes(payload):
        for original, replacement in replacements.items():
            payload = payload.replace(original.encode(), replacement.encode())
        return payload

    for item in task["files"]:
        content = base64.b64decode(item["content_base64"])
        if zipfile.is_zipfile(io.BytesIO(content)):
            stream = io.BytesIO()
            with (
                zipfile.ZipFile(io.BytesIO(content)) as source,
                zipfile.ZipFile(stream, "w") as target,
            ):
                for name in source.namelist():
                    target.writestr(name, replace_bytes(source.read(name)))
            content = stable_zip(stream.getvalue())
        else:
            content = replace_bytes(content)
        item["content_base64"] = base64.b64encode(content).decode()
    gold_text = json.dumps(gold, ensure_ascii=False)
    for original, replacement in replacements.items():
        gold_text = gold_text.replace(original, replacement)
    gold = json.loads(gold_text)
    return {
        "case_key": key,
        "revision": 3,
        "agent": agent,
        "track": track,
        "title": title,
        "source_family": f"synthetic-{key}",
        "split": "holdout" if index % 3 == 0 else "development",
        "visibility": "public_synthetic",
        "task": task,
        "provenance": {
            "kind": "synthetic",
            "basis": "人工設計的公開合成案例；不含真實人員或業務資料。",
        },
        "answer": gold,
    }


def public_cases():
    cases = []
    extensions = ["html", "htm", "json", "csv", "xlsx", "xlsm", "docx"]
    for index, ext in enumerate(extensions, 1):
        locator = {
            "html": "text_line:2",
            "htm": "text_line:2",
            "json": "json:/event",
            "csv": "row:2",
            "xlsx": "sheet:1/row:2",
            "xlsm": "sheet:1/row:2",
            "docx": "paragraph:2",
        }[ext]
        checks = [
            check("summary.period_start", "2026-08-24"),
            check("summary.period_end", "2026-08-30"),
            check("summary.version", 1),
            check("summary.record_count", 2),
            check("summary.evidence_status", "unverified_source"),
            check("summary.issues", [], "set_eq"),
        ]
        cases.append(
            candidate(
                f"C-S{index:02}",
                "collection",
                "standard",
                f"新規範 · {ext.upper()} 內容與來源定位",
                {"files": [file(STEM + "." + ext, content_for(ext))]},
                answer(checks, evidence=[{"locator": locator, "quote": TEXT}]),
                index,
            )
        )
    extras = [
        (
            "ISO 週次獨立辨識",
            "ORG01_OFF01_周报_2026-W35_v01.html",
            "<p>PROJECT_001</p>",
            "2026-08-24",
            "2026-08-30",
            1,
            "weekly_report",
        ),
        (
            "月報與週報區分",
            "ORG01_OFF01_月报_2026-08_v01.html",
            "<p>PROJECT_001</p>",
            "2026-08-01",
            "2026-08-31",
            1,
            "monthly_report",
        ),
        (
            "確認表工作月份",
            "ORG01_OFF01_确认表_2026-08_v01.html",
            "<p>PROJECT_001</p>",
            "2026-08-01",
            "2026-08-31",
            1,
            "confirmation",
        ),
        (
            "正文補足期間",
            "ORG01_OFF01_周报_v02.html",
            f"<p>{PERIOD}</p><p>PROJECT_001</p>",
            "2026-08-24",
            "2026-08-30",
            2,
            "weekly_report",
        ),
        (
            "跨月週期間",
            "ORG01_OFF01_周报_2026-W31_2026-07-27_2026-08-02_v03.html",
            "<p>Reporting period: 2026-07-27 to 2026-08-02</p><p>PROJECT_001 continuation</p>",
            "2026-07-27",
            "2026-08-02",
            3,
            "weekly_report",
        ),
    ]
    for index, (title, name, body, start, end, version, kind) in enumerate(extras, 8):
        cases.append(
            candidate(
                f"C-S{index:02}",
                "collection",
                "standard",
                title,
                {"files": [file(name, body.encode())]},
                answer(
                    [
                        check("summary.period_start", start),
                        check("summary.period_end", end),
                        check("summary.version", version),
                        check("summary.document_type", kind),
                        check("summary.issues", [], "set_eq"),
                    ],
                    evidence=[{"quote": "PROJECT_001"}],
                ),
                index,
            )
        )
    anomalies = [
        (
            "提交日期不得當工作期間",
            file("ORG01_OFF01_周报_2026-08-31_v01.html", b"<p>PROJECT_001</p>"),
            "DATE_MAY_BE_PUBLICATION",
        ),
        ("週次與正文矛盾", file("ORG01_OFF01_周报_2026-W34_v01.html"), "DATE_WEEK_CONFLICT"),
        (
            "檔名與正文期間衝突",
            file(STEM + ".html", content_for("html", "Reporting period: 2026-08-17 to 2026-08-23")),
            "FILENAME_BODY_PERIOD_CONFLICT",
        ),
        ("缺少版本需確認", file("ORG01_OFF01_周报_2026-W35.html"), "VERSION_MISSING_OR_INVALID"),
        (
            "偽裝 Excel 拒收",
            file(STEM + ".xlsx", b"not an office archive"),
            "INVALID_OFFICE_OR_ENCRYPTED",
        ),
        ("空檔不得成功", file(STEM + ".html", b""), "EMPTY_OR_OVERSIZED_FILE"),
        ("不支援 PDF 明確拒收", file(STEM + ".pdf", b"%PDF-1.4"), "FORMAT_NOT_SUPPORTED_YET"),
        (
            "公式不得當已計算結果",
            file(STEM + ".xlsx", content_for("xlsx", text="=SUM(1,2)")),
            "FORMULA_NOT_EVALUATED",
        ),
        (
            "僅腳本內容不能解析成功",
            file(STEM + ".html", b"<html><script>secret()</script></html>"),
            "NO_EXTRACTABLE_CONTENT",
        ),
        ("損壞 JSON 不得吞錯", file(STEM + ".json", b"{broken"), "UNREADABLE_OR_DAMAGED_FILE"),
    ]
    for index, (title, item, issue) in enumerate(anomalies, 1):
        cases.append(
            candidate(
                f"C-A{index:02}",
                "collection",
                "anomaly",
                title,
                {"files": [item]},
                answer(
                    [check("summary.issues", issue, "contains")],
                    True,
                    basis=f"注入異常需回報 {issue}，不得自動歸檔。",
                ),
                index,
            )
        )
    for index, (title, item) in enumerate(
        [
            (
                "脚本忽略但正文完整",
                file(STEM + ".html", content_for("html") + b"<script>return 'PASS';</script>"),
            ),
            ("提交在下週，正文明列上週", file("ORG01_OFF01_周报_2026-08-31_v01.html")),
        ],
        11,
    ):
        cases.append(
            candidate(
                f"C-A{index:02}",
                "collection",
                "anomaly",
                title,
                {"files": [item]},
                answer(
                    [
                        check("summary.period_start", "2026-08-24"),
                        check("summary.period_end", "2026-08-30"),
                        check("summary.record_count", 2),
                    ],
                    evidence=[{"quote": TEXT}],
                ),
                index,
            )
        )
    base = file()
    changed = file(content=content_for("html", text="PROJECT_001 revision"))
    v2 = file(
        STEM.replace("v01", "v02") + ".html", content_for("html", text="PROJECT_001 revision")
    )
    missing = file("ORG01_OFF01_周报_2026-W35.html")
    otherperiod = file("ORG01_OFF01_周报_2026-W36_v01.html", b"<p>PROJECT_001</p>")
    onlyweek = file("ORG01_OFF01_周报_2026-W35_v01.html", b"<p>PROJECT_001</p>")
    flows = [
        ("正常收件停在 NORMALIZED", [base], [0], ["normalized"], 1, {}),
        ("同 Telegram 更新冪等", [base], [0, 0], ["normalized"], 1, {"same_delivery": True}),
        ("相同檔案重傳只歸檔一次", [base], [0, 0], ["normalized", "duplicate"], 1, {}),
        ("新版本保留歷史", [base, v2], [0, 1], ["normalized", "normalized"], 2, {"latest": [2]}),
        (
            "同版本不同內容升級人工",
            [base, changed],
            [0, 1],
            ["normalized", "awaiting_confirmation"],
            1,
            {"issue": "VERSION_CONTENT_CONFLICT"},
        ),
        (
            "跨週重用相同內容升級",
            [onlyweek, otherperiod],
            [0, 1],
            ["normalized", "awaiting_confirmation"],
            1,
            {"issue": "CROSS_PERIOD_CONTENT_REUSE"},
        ),
        ("晚到舊版本不降級", [v2, base], [0, 1], ["normalized", "normalized"], 2, {"latest": [2]}),
        ("缺件等待確認不放行", [missing], [0], ["awaiting_confirmation"], 0, {}),
        (
            "公司與責任人不符不可歸檔",
            [file(STEM.replace("ORG01", "ORG02") + ".html")],
            [0],
            ["awaiting_confirmation"],
            0,
            {},
        ),
        (
            "傳輸失敗後恢復且不重複",
            [base],
            [0],
            ["normalized"],
            1,
            {"transport_failures": {"0": 1}, "attempts": 2, "replay_collection": True},
        ),
        (
            "傳輸重試耗盡必須失敗",
            [base],
            [0],
            ["processing_failed"],
            0,
            {"transport_failures": {"0": 3}, "failed": 1, "attempts": 3},
        ),
        (
            "最後一次工作者崩潰可被發現",
            [base],
            [0],
            ["processing_failed"],
            0,
            {"crash_final_attempt": True, "failed": 1, "attempts": 3},
        ),
    ]
    for index, (title, files, order, statuses, source_count, options) in enumerate(flows, 1):
        task = {
            "files": files,
            "company_code": "ORG01",
            "officer_code": "OFF01",
            "deliveries": [
                {
                    "file": n,
                    "key": "delivery-0" if options.get("same_delivery") else f"delivery-{i}",
                }
                for i, n in enumerate(order)
            ],
        }
        task.update(
            {
                k: v
                for k, v in options.items()
                if k in ("transport_failures", "crash_final_attempt", "replay_collection")
            }
        )
        checks = [
            check("statuses", statuses),
            check("source_count", source_count),
            check("receipt_count", len(statuses)),
            check("failed_jobs", options.get("failed", 0)),
            check("scope", "intake_only"),
        ]
        if options.get("issue"):
            checks.append(check("issues.1", options["issue"], "contains"))
        if "latest" in options:
            checks.append(check("latest_versions", options["latest"]))
        if "attempts" in options:
            checks.append(check("max_attempts", options["attempts"]))
        cases.append(
            candidate(
                f"S-F{index:02}",
                "supervisor",
                "workflow",
                title,
                task,
                answer(
                    checks,
                    any(s not in ("normalized", "duplicate") for s in statuses),
                    evidence=[{"quote": "PROJECT_001"}] if source_count else [],
                    basis="依輸入交付順序與故障注入，檢查真實收件、佇列與來源版本狀態；不代表完整總管 DAG。",
                ),
                index,
            )
        )
    return cases


def seed_cases(session, cases):
    inserted = []
    for spec in cases:
        existing = session.scalar(
            select(AcceptanceCase).where(
                AcceptanceCase.case_key == spec["case_key"],
                AcceptanceCase.revision == spec["revision"],
            )
        )
        if existing:
            if digest(existing.task) != digest(spec["task"]):
                raise ValueError("CASE_IMMUTABLE_INCREMENT_REVISION")
            continue
        family = session.scalar(
            select(AcceptanceCase)
            .where(AcceptanceCase.source_family == spec["source_family"])
            .limit(1)
        )
        if family and family.split != spec["split"]:
            raise ValueError("SOURCE_FAMILY_SPLIT_LEAKAGE")
        case = AcceptanceCase(**{k: v for k, v in spec.items() if k != "answer"})
        session.add(case)
        session.flush()
        add_answer(session, case.id, spec["answer"])
        inserted.append(case.id)
    return inserted
