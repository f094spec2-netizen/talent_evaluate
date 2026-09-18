import calendar
import json
import re
from datetime import date, timedelta

DATE = r"(?<!\d)(\d{4})[-_/年](\d{1,2})[-_/月](\d{1,2})(?:日)?(?!\d)"
WEEK = r"(?<![A-Za-z])(?:\d{4}[-_ ]?)?[Ww](\d{1,2})(?!\d)"


def parse_dates(text: str) -> tuple[list[date], list[str]]:
    values, issues = [], []
    for match in re.finditer(DATE, text):
        try:
            values.append(date(*map(int, match.groups())))
        except ValueError:
            issues.append("INVALID_DATE")
    return values, issues


def infer_period(filename: str, records: list[dict]) -> dict:
    """ISO weeks for this pilot; publication dates must not silently define a report period."""
    issues: list[str] = []
    kind = None
    if any(tag in filename.lower() for tag in ("周报", "週報", "weekly")):
        kind = "weekly_report"
    elif any(tag in filename.lower() for tag in ("月报", "月報", "monthly")):
        kind = "monthly_report"
    elif any(tag in filename.lower() for tag in ("确认表", "確認表", "confirmation")):
        kind = "confirmation"
    if not kind:
        issues.append("DOCUMENT_TYPE_MISSING")

    versions = re.findall(r"(?:^|[_ .-])v(\d+)(?=[_. -]|$)", filename, re.I)
    version = int(versions[0]) if len(versions) == 1 else None
    if not version or version > 100000:
        version = None
        issues.append("VERSION_MISSING_OR_INVALID")

    file_dates, date_errors = parse_dates(filename)
    issues.extend(date_errors)
    file_range = (file_dates[0], file_dates[1]) if len(file_dates) == 2 else None
    if len(file_dates) > 2:
        issues.append("MULTIPLE_FILENAME_DATES")

    # Only explicitly labelled headers are considered; dates in task rows are not report dates.
    body_ranges = []
    for record in records[:40]:
        text = record["text"]
        if record.get("locator") in ("json:/period", "json:/reporting_period"):
            value = json.loads(text)
            period = value.get("period", value.get("reporting_period"))
            if isinstance(period, dict):
                text = f"Reporting period: {period.get('start_date', '')} to {period.get('end_date', '')}"
        if re.match(
            r"^\s*(?:报告期间|報告期間|统计期间|統計期間|报告周期|報告週期|reporting period)\s*[:：]",
            text,
            re.I,
        ):
            dates, errors = parse_dates(text)
            issues.extend(errors)
            if len(dates) == 2:
                body_ranges.append((dates[0], dates[1]))
            else:
                issues.append("BODY_PERIOD_UNREADABLE")
    body_ranges = list(dict.fromkeys(body_ranges))
    if len(body_ranges) > 1:
        issues.append("MULTIPLE_BODY_PERIODS")
    body_range = body_ranges[0] if len(body_ranges) == 1 else None
    if file_range and body_range and file_range != body_range:
        issues.append("FILENAME_BODY_PERIOD_CONFLICT")

    proposed = body_range or file_range
    basis = "labelled_body" if body_range else "filename_range" if file_range else None
    week_matches = re.findall(WEEK, filename)
    years = re.findall(r"(?<!\d)(20\d{2})(?!\d)", filename)
    week_range = None
    if week_matches:
        if len(set(week_matches)) > 1 or not years:
            issues.append("WEEK_YEAR_AMBIGUOUS")
        else:
            try:
                monday = date.fromisocalendar(int(years[0]), int(week_matches[0]), 1)
                week_range = (monday, monday + timedelta(days=6))
            except ValueError:
                issues.append("INVALID_ISO_WEEK")
    if kind == "weekly_report":
        if not proposed and week_range:
            proposed, basis = week_range, "filename_iso_week"
        if not proposed and len(file_dates) == 1:
            monday = file_dates[0] - timedelta(days=file_dates[0].weekday())
            proposed, basis = (monday, monday + timedelta(days=6)), "date_only_candidate"
            issues.append("DATE_MAY_BE_PUBLICATION")
        if proposed:
            if (
                proposed[1] < proposed[0]
                or (proposed[1] - proposed[0]).days != 6
                or proposed[0].weekday() != 0
            ):
                issues.append("NON_ISO_WEEK_RANGE")
            if week_range and week_range != proposed:
                issues.append("DATE_WEEK_CONFLICT")
            # A single date alongside an explicit Wxx can be a publication date, but still needs review.
            if (
                len(file_dates) == 1
                and week_range
                and not (week_range[0] <= file_dates[0] <= week_range[1])
            ):
                issues.append("DATE_WEEK_CONFLICT")
    elif kind in ("monthly_report", "confirmation"):
        matches = re.findall(r"(?<!\d)(20\d{2})[-_年](\d{1,2})(?:月)?(?!\d)", filename)
        if body_range and not file_dates and len(set(matches)) == 1:
            year, month = map(int, matches[0])
            if (body_range[0].year, body_range[0].month) != (year, month):
                issues.append("FILENAME_BODY_PERIOD_CONFLICT")
        if not proposed:
            if len(set(matches)) == 1:
                year, month = map(int, matches[0])
                try:
                    proposed = (
                        date(year, month, 1),
                        date(year, month, calendar.monthrange(year, month)[1]),
                    )
                    basis = "filename_month"
                    if file_dates:
                        issues.append("DATE_MAY_BE_PUBLICATION")
                except ValueError:
                    issues.append("INVALID_MONTH")
        if proposed:
            start, end = proposed
            if start.day != 1 or end != date(
                start.year, start.month, calendar.monthrange(start.year, start.month)[1]
            ):
                issues.append("NON_CALENDAR_MONTH_RANGE")

    if not proposed:
        issues.append("PERIOD_MISSING")
    return {
        "document_type": kind,
        "version": version,
        "period_start": proposed[0].isoformat() if proposed else None,
        "period_end": proposed[1].isoformat() if proposed else None,
        "iso_week": f"{proposed[0].isocalendar().year}-W{proposed[0].isocalendar().week:02d}"
        if proposed and kind == "weekly_report"
        else None,
        "period_basis": basis,
        "filename_period": [d.isoformat() for d in file_range] if file_range else None,
        "body_period": [d.isoformat() for d in body_range] if body_range else None,
        "issues": sorted(set(issues)),
    }
