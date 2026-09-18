from dataclasses import dataclass

from app.parsers import parse_file
from app.periods import infer_period

RULE_VERSION = "intake-2026-09-18.1"


@dataclass
class CollectionResult:
    summary: dict
    records: list[dict]


def collect(filename: str, content: bytes) -> CollectionResult:
    records, warnings = parse_file(filename, content)
    period = infer_period(filename, records)
    # Formula text must not be mistaken for a computed result.
    if "FORMULA_NOT_EVALUATED" in warnings:
        period["issues"].append("FORMULA_NOT_EVALUATED")
    return CollectionResult(
        {
            "agent_type": "collection",
            "rule_version": RULE_VERSION,
            "model_trace_id": None,
            "record_count": len(records),
            "warnings": warnings,
            "source_content_is_untrusted": True,
            "evidence_status": "unverified_source",
            **period,
            "recommended_route": "yellow" if period["issues"] else "green",
        },
        records,
    )
