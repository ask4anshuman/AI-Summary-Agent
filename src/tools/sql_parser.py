import re
from collections import Counter

DDL_PATTERN = re.compile(r"\b(create|alter|drop|truncate|rename)\b", re.IGNORECASE)
DML_PATTERN = re.compile(r"\b(insert|update|delete|merge|select)\b", re.IGNORECASE)
PLSQL_PATTERN = re.compile(
    r"\b(create\s+or\s+replace\s+(procedure|function|package|trigger)|declare|begin|exception|end;)\b",
    re.IGNORECASE,
)

OBJECT_PATTERNS = [
    re.compile(r"\b(?:create|alter|drop)\s+table\s+([\w\.\"]+)", re.IGNORECASE),
    re.compile(r"\binsert\s+into\s+([\w\.\"]+)", re.IGNORECASE),
    re.compile(r"\bupdate\s+([\w\.\"]+)", re.IGNORECASE),
    re.compile(r"\bdelete\s+from\s+([\w\.\"]+)", re.IGNORECASE),
    re.compile(r"\bcreate\s+or\s+replace\s+procedure\s+([\w\.\"]+)", re.IGNORECASE),
    re.compile(r"\bcreate\s+or\s+replace\s+function\s+([\w\.\"]+)", re.IGNORECASE),
    re.compile(r"\bcreate\s+or\s+replace\s+trigger\s+([\w\.\"]+)", re.IGNORECASE),
    re.compile(r"\bcreate\s+or\s+replace\s+package\s+([\w\.\"]+)", re.IGNORECASE),
]

OBJECT_TYPE_PATTERNS = [
    (re.compile(r"\bcreate\s+(?:or\s+replace\s+)?table\b", re.IGNORECASE), "TABLE"),
    (re.compile(r"\bcreate\s+(?:or\s+replace\s+)?function\b", re.IGNORECASE), "FUNCTION"),
    (re.compile(r"\bcreate\s+(?:or\s+replace\s+)?procedure\b", re.IGNORECASE), "PROCEDURE"),
    (re.compile(r"\bcreate\s+(?:or\s+replace\s+)?trigger\b", re.IGNORECASE), "TRIGGER"),
    (re.compile(r"\bcreate\s+(?:or\s+replace\s+)?package\b", re.IGNORECASE), "PACKAGE"),
    (re.compile(r"\bview\b", re.IGNORECASE), "VIEW"),
]

TABLE_REFERENCE_PATTERNS = [
    re.compile(r"\bfrom\s+([\w\.\"]+)", re.IGNORECASE),
    re.compile(r"\bjoin\s+([\w\.\"]+)", re.IGNORECASE),
    re.compile(r"\binsert\s+into\s+([\w\.\"]+)", re.IGNORECASE),
    re.compile(r"\bupdate\s+([\w\.\"]+)", re.IGNORECASE),
    re.compile(r"\bdelete\s+from\s+([\w\.\"]+)", re.IGNORECASE),
    re.compile(r"\bmerge\s+into\s+([\w\.\"]+)", re.IGNORECASE),
    re.compile(r"\bcreate\s+table\s+([\w\.\"]+)", re.IGNORECASE),
    re.compile(r"\balter\s+table\s+([\w\.\"]+)", re.IGNORECASE),
]

JOIN_PATTERN = re.compile(
    r"\b(?:inner|left|right|full|cross)?\s*join\s+[\w\.\"]+(?:\s+\w+)?\s+on\s+.*?(?=\b(?:inner|left|right|full|cross)?\s*join\b|\bwhere\b|\bgroup\b|\border\b|\bhaving\b|;|$)",
    re.IGNORECASE | re.DOTALL,
)

FILTER_PATTERNS = [
    re.compile(r"\bwhere\s+.*?(?=\bgroup\b|\border\b|\bhaving\b|;|$)", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bhaving\s+.*?(?=\border\b|;|$)", re.IGNORECASE | re.DOTALL),
]


def detect_change_type(sql_text: str) -> str:
    if not sql_text.strip():
        return "Unknown"

    has_ddl = bool(DDL_PATTERN.search(sql_text))
    has_dml = bool(DML_PATTERN.search(sql_text))
    has_plsql = bool(PLSQL_PATTERN.search(sql_text))

    tags = []
    if has_ddl:
        tags.append("DDL")
    if has_dml:
        tags.append("DML")
    if has_plsql:
        tags.append("PLSQL")

    if not tags:
        return "Unknown"
    if len(tags) == 1:
        return tags[0]
    return "Mixed (" + ", ".join(tags) + ")"


def extract_affected_objects(sql_text: str) -> list[str]:
    found: list[str] = []
    for pattern in OBJECT_PATTERNS:
        for match in pattern.finditer(sql_text):
            candidate = match.group(1).strip('"')
            found.append(candidate)

    deduped = sorted(set(found))
    return deduped


def analyze_operation_mix(sql_text: str) -> dict[str, int]:
    ops = re.findall(r"\b(create|alter|drop|truncate|rename|insert|update|delete|merge|select)\b", sql_text, re.IGNORECASE)
    counts = Counter(op.upper() for op in ops)
    return dict(counts)


def estimate_impact_level(sql_text: str, affected_objects: list[str]) -> str:
    text = sql_text.lower()
    high_risk_tokens = ["drop table", "truncate", "drop column", "delete from"]
    medium_risk_tokens = ["alter table", "update", "merge", "create or replace trigger"]

    if any(token in text for token in high_risk_tokens):
        return "high"
    if any(token in text for token in medium_risk_tokens):
        return "medium"
    if affected_objects:
        return "medium"
    return "low"


def basic_sql_sanity_checks(sql_text: str) -> list[str]:
    warnings: list[str] = []
    if not sql_text.strip():
        warnings.append("SQL content is empty.")
        return warnings

    begin_count = len(re.findall(r"\bbegin\b", sql_text, re.IGNORECASE))
    end_count = len(re.findall(r"\bend;\b", sql_text, re.IGNORECASE))
    if begin_count > end_count:
        warnings.append("PL/SQL block may be missing END; statement.")

    if sql_text.count("(") != sql_text.count(")"):
        warnings.append("Parentheses appear unbalanced.")

    return warnings


def extract_object_types(sql_text: str) -> list[str]:
    found: list[str] = []
    for pattern, object_type in OBJECT_TYPE_PATTERNS:
        if pattern.search(sql_text):
            found.append(object_type)

    if DML_PATTERN.search(sql_text):
        found.append("DML")

    return sorted(set(found)) or ["UNKNOWN"]


def extract_table_details(sql_text: str) -> list[str]:
    found: list[str] = []
    for pattern in TABLE_REFERENCE_PATTERNS:
        for match in pattern.finditer(sql_text):
            found.append(match.group(1).strip('"'))
    return sorted(set(found))


def extract_join_details(sql_text: str) -> list[str]:
    return [_collapse_sql_whitespace(match.group(0)) for match in JOIN_PATTERN.finditer(sql_text)]


def extract_filter_details(sql_text: str) -> list[str]:
    found: list[str] = []
    for pattern in FILTER_PATTERNS:
        found.extend(_collapse_sql_whitespace(match.group(0)) for match in pattern.finditer(sql_text))
    return found


def _collapse_sql_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
