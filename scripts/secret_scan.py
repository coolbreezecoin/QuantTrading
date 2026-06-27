from __future__ import annotations

import re
import sys
from pathlib import Path

DENYLIST_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
}

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|api[_-]?secret|passphrase|token)\s*[:=]\s*['\"][^'\"]{12,}['\"]"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----"),
]


def iter_text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if any(part in DENYLIST_DIRS for part in path.parts):
            continue
        if path.is_file():
            files.append(path)
    return files


def scan_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []

    findings: list[str] = []
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(f"{path}: matched {pattern.pattern}")
    return findings


def main() -> int:
    root = Path.cwd()
    findings: list[str] = []
    for path in iter_text_files(root):
        findings.extend(scan_file(path))

    if findings:
        print("Potential secrets found:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

