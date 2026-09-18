"""No LLM judge. Exact fields + source locators + optional audited human rubric."""

from collections import defaultdict

SCORER_VERSION = "exact-evidence-2"


def lookup(value, path):
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def score(answer, actual):
    differences = []
    expected_disposition = "human" if answer["expected_human"] else "automatic"
    if actual.get("disposition") != expected_disposition:
        differences.append(
            {
                "path": "disposition",
                "value": expected_disposition,
                "actual": actual.get("disposition"),
                "critical": answer["expected_human"]
                or actual.get("disposition") not in ("automatic", "human"),
            }
        )
    for check in answer["checks"]:
        got = lookup(actual, check["path"])
        op, expected = check.get("op", "eq"), check["value"]
        matched = (
            got == expected
            if op == "eq"
            else isinstance(got, list) and expected in got
            if op == "contains"
            else isinstance(got, list) and set(got) == set(expected)
            if op == "set_eq"
            else isinstance(got, (int, float)) and got >= expected
            if op == "gte"
            else False
        )
        if not matched:
            if (
                check["path"] == "disposition"
                and differences
                and differences[0]["path"] == "disposition"
            ):
                differences[0]["critical"] = differences[0]["critical"] or check.get(
                    "critical", True
                )
                continue
            differences.append({**check, "actual": got})
    records = actual.get("records", [])
    evidence_errors = []
    for evidence in answer.get("evidence", []):
        found = any(
            (not evidence.get("locator") or row.get("locator") == evidence["locator"])
            and evidence["quote"] in row.get("text", "")
            for row in records
        )
        if not found:
            evidence_errors.append(evidence)
    # Empty, repeated or missing source locations cannot be deemed traceable.
    locators = [row.get("locator") for row in records]
    if records and (not all(locators) or len(set(locators)) != len(locators)):
        evidence_errors.append({"quote": "來源定位缺漏或重複"})
    critical = sum(bool(d.get("critical", True)) for d in differences) + len(evidence_errors)
    return {
        "correct": not differences and not evidence_errors,
        "differences": differences,
        "evidence_errors": evidence_errors,
        "critical_errors": critical,
        "evidence_ok": not evidence_errors,
        "human_required": bool(answer.get("rubric")),
    }


def metrics(results, required, formal, required_decidable=None):
    """Required includes missing cases, preventing cherry-picked/subset passing."""
    groups = defaultdict(list)
    for result in results:
        groups[result["snapshot"]["track"]].append(result)
    reports = {}
    for track, ids in required.items():
        rows = groups[track]
        done = [r for r in rows if r["state"] == "completed"]
        automatic = [r for r in done if r["actual"].get("disposition") == "automatic"]

        def correct(r):
            s = r["score"]
            return (
                s.get("correct", False)
                and r.get("adjudication") != "return"
                and (not s.get("human_required") or r.get("adjudication") == "accept")
            )

        decidable = [r for r in rows if not r["snapshot"]["answer"]["expected_human"]]
        covered = [
            r for r in decidable if r in done and r["actual"].get("disposition") == "automatic"
        ]
        precision = sum(correct(r) for r in automatic) / len(automatic) if automatic else None
        denominator = (
            len(required_decidable[track]) if required_decidable is not None else len(decidable)
        )
        coverage = len(covered) / denominator if denominator else None
        critical = sum(r["score"].get("critical_errors", 0) for r in done)
        failed = sum(r["state"] == "failed" for r in rows)
        evidence_ok = len(done) == len(rows) and all(r["score"].get("evidence_ok") for r in done)
        complete = bool(ids) and set(ids) == {r["case_id"] for r in done}
        approved = all(r["snapshot"]["approved"] for r in rows) and bool(rows)
        # Expected-human cases must actually escalate correctly; they never improve auto coverage.
        human_ok = all(
            correct(r) and r["actual"].get("disposition") == "human"
            for r in done
            if r["snapshot"]["answer"]["expected_human"]
        )
        semantic_ok = all(
            r.get("adjudication") != "return"
            and (not r["score"].get("human_required") or r.get("adjudication") == "accept")
            for r in done
        )
        thresholds = (
            precision is not None and precision >= 0.95 and coverage is not None and coverage >= 0.8
        )
        # Tracks with only required-human cases have N/A automation metrics, not fictitious 100%.
        if not denominator:
            thresholds = not automatic and human_ok
        passed = bool(
            formal
            and complete
            and approved
            and not failed
            and critical == 0
            and evidence_ok
            and human_ok
            and semantic_ok
            and thresholds
        )
        reports[track] = {
            "required": len(ids),
            "selected": len(rows),
            "completed": len(done),
            "automatic": len(automatic),
            "correct_automatic": sum(correct(r) for r in automatic),
            "decidable": denominator,
            "covered": len(covered),
            "precision": precision,
            "coverage": coverage,
            "critical_errors": critical,
            "failed": failed,
            "complete": complete,
            "approved": approved,
            "evidence_ok": evidence_ok,
            "human_ok": human_ok,
            "passed": passed,
        }
    return reports
