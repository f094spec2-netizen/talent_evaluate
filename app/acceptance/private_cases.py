"""Local-only structural deidentification. Never publish output without a separate review.

The operator supplies a private manifest with source paths and independently drafted gold.
Preserves HTML layout, period labels/dates, and repeated text identity; replaces business prose.
This is a collection benchmark, NOT a contribution/potential semantic benchmark.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup, Comment, Doctype, NavigableString

from app.acceptance.fixtures import file

# Only reporting metadata survives. Names, project prose, figures, URLs, attributes do not.
METADATA = re.compile(
    r"20\d{2}[-_/年.]\d{1,2}(?:[-_/月.]\d{1,2}日?)?|(?<!\d)\d{1,2}[-/]\d{1,2}(?!\d)|"
    r"(?<![A-Za-z])W\d{1,2}(?!\d)|"
    r"报告期间|報告期間|统计期间|統計期間|报告周期|報告週期|统计周期|統計週期|覆盖周期|覆蓋週期|"
    r"工作周期|工作期間|汇报周期|Reporting period|周报|週報|月报|月報|工作报告|生成时间|编制日期|日期|"
    r"REPORT-ORG|LEVEL|TYPE|DATE|(?<![A-Za-z])L[123](?!\d)|[:：~～—–至_\-\[\]()/<>|]+|\s+",
    re.I,
)


def anonymize(source, tokens):
    def mask(text):
        def token(value):
            if not value.strip():
                return value
            key = value.strip()
            if key not in tokens:
                tokens[key] = f"TEXT_{len(tokens) + 1:05d}"
            return tokens[key]

        result, previous = [], 0
        for match in METADATA.finditer(text):
            result.extend((token(text[previous : match.start()]), match.group(0)))
            previous = match.end()
        result.append(token(text[previous:]))
        return "".join(result)

    soup = BeautifulSoup(source, "html.parser")
    for element in soup(["script", "style", "noscript", "iframe", "object", "link", "meta", "img"]):
        element.decompose()
    for element in soup.find_all(True):
        element.attrs = {}
    for text in list(soup.find_all(string=True)):
        if isinstance(text, Comment):
            text.extract()
        elif isinstance(text, Doctype):
            continue
        elif isinstance(text, NavigableString):
            text.replace_with(mask(str(text)))
    return str(soup).encode("utf-8")


def prepare(manifest_path, output):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tokens, cases, origins = {}, [], {}
    for index, item in enumerate(manifest, 1):
        path = Path(item["source"])
        raw = path.read_bytes()
        sanitized = anonymize(raw.decode("utf-8-sig"), tokens)
        key = f"C-H{index:02}"
        origins[key] = {
            "original_path": str(path),
            "original_sha256": hashlib.sha256(raw).hexdigest(),
        }
        gold = item["answer"]
        cases.append(
            {
                "case_key": key,
                "revision": item.get("revision", 1),
                "agent": "collection",
                "track": "historical",
                "title": item["title"],
                "source_family": item["source_family"],
                "split": item["split"],
                "visibility": "private_derived",
                "task": {"files": [file(item["filename"], sanitized)]},
                "provenance": {
                    "kind": "private_derived",
                    "source_code": key,
                    "source_sha256": origins[key]["original_sha256"],
                    "sanitized_sha256": hashlib.sha256(sanitized).hexdigest(),
                    "method": "保留 HTML 結構、期間標籤與日期；其他文字一致代碼化；移除腳本、屬性與連結。原文及對照表僅本地私有保存。",
                    "scope": "只驗證收集與期間辨識，不能用於貢獻／潛力語義評估。",
                },
                "answer": gold,
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    mapping = json.dumps({"origins": origins, "tokens": tokens}, ensure_ascii=False, indent=2)
    map_hash = hashlib.sha256(mapping.encode()).hexdigest()[:16]
    output.with_name(f"deidentification-map.{map_hash}.private.json").write_text(
        mapping,
        encoding="utf-8",
    )
    print(
        f"Prepared {len(cases)} PRIVATE cases. Human gold approval and privacy review remain required."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.manifest, args.output)
