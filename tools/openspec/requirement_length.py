#!/usr/bin/env python3
"""Fail when an active change's delta has an ADDED or MODIFIED requirement over 500 characters.

Used by the reusable workflow openspec-docs-check.yml in Frazzled-Productions/.github; also runs
locally against any checkout (the current directory, or OPENSPEC_ROOT).

  requirement_length.py        check every openspec/changes/<name>/specs/**/spec.md (not archive/)

Why (ops #313): `openspec validate --changes --strict` (1.14.3) does not length-check a MODIFIED
requirement, and only warns on an ADDED one, while `openspec validate --specs --strict` after the
archive fails on any requirement over 500 characters. So the PR goes green and the archive fails on
main after merge.

The text is measured as OpenSpec measures it (dist/core/parsers/requirement-text.js,
extractRequirementBody, and MAX_REQUIREMENT_TEXT_LENGTH in core/validation/constants.js): the lines
after the `### Requirement:` header up to the first header, skipping blank lines and fenced code,
each trimmed and joined with a newline; `**Key**: value` metadata lines are left out unless they are
the whole body; an empty body falls back to the header title. Length is in UTF-16 code units, as
JavaScript's String.length counts. Over 500 fails; exactly 500 passes.
"""
import os
import pathlib
import re
import sys

MAX = 500
ROOT = pathlib.Path(os.environ.get("OPENSPEC_ROOT", ".")).resolve()
REQUIREMENT_HEADER = re.compile(r"^###\s*Requirement:\s*(.+)\s*$", re.I)
SECTION_HEADER = re.compile(r"^##\s+(.+?)\s*$")
HEADER_LINE = re.compile(r"^#{1,6}\s")
BLOCK_END = re.compile(r"^#{1,3}\s")
METADATA_LINE = re.compile(r"^\*\*[^*]+\*\*:")
CHECKED_SECTIONS = {"added requirements", "modified requirements"}


def fence_mask(lines):
    """True for each line inside a fenced code block, fence lines included (code-fence.js)."""
    mask, active = [False] * len(lines), None
    for i, line in enumerate(lines):
        if active is None:
            m = re.match(r"^\s*(`{3,}|~{3,})", line)
            if m:
                active = (m.group(1)[0], len(m.group(1)))
                mask[i] = True
            continue
        mask[i] = True
        m = re.match(r"^\s*(`{3,}|~{3,})\s*$", line)
        if m and m.group(1)[0] == active[0] and len(m.group(1)) >= active[1]:
            active = None
    return mask


def requirement_text(title, body_lines):
    """OpenSpec's extractRequirementText: the body up to the first header, else the title."""
    mask = fence_mask(body_lines)
    captured, metadata = [], []
    for i, line in enumerate(body_lines):
        if mask[i]:
            continue
        if HEADER_LINE.match(line):
            break
        trimmed = line.strip()
        if not trimmed:
            continue
        (metadata if METADATA_LINE.match(trimmed) else captured).append(trimmed)
    return "\n".join(captured) or "\n".join(metadata) or title.strip()


def js_length(text):
    return len(text.encode("utf-16-le")) // 2


def requirements(text):
    """Yield (section, title, text) for each `### Requirement:` block in a delta."""
    lines = text.split("\n")
    mask = fence_mask(lines)
    section = None
    for i, line in enumerate(lines):
        if mask[i]:
            continue
        m = SECTION_HEADER.match(line)
        if m:
            section = m.group(1).rstrip("#").strip().lower()
            continue
        m = REQUIREMENT_HEADER.match(line)
        if not m:
            continue
        end = i + 1
        while end < len(lines) and (mask[end] or not BLOCK_END.match(lines[end])):
            end += 1
        title = m.group(1).rstrip("#").strip()
        yield section, title, requirement_text(title, lines[i + 1:end])


def check(root=None):
    """Print each over-long ADDED or MODIFIED requirement; return the problems found."""
    root = pathlib.Path(root or ROOT)
    changes = root / "openspec" / "changes"
    problems = []
    if not changes.is_dir():
        return problems
    for change in sorted(p for p in changes.iterdir() if p.is_dir() and p.name != "archive" and not p.name.startswith(".")):
        for spec in sorted((change / "specs").rglob("spec.md")):
            for section, title, text in requirements(spec.read_text(encoding="utf-8")):
                if section not in CHECKED_SECTIONS:
                    continue
                n = js_length(text)
                if n > MAX:
                    kind = section.split()[0].upper()
                    problems.append(
                        f"{spec.relative_to(root)}: {kind} requirement \"{title}\" is {n} characters, over "
                        f"OpenSpec's {MAX} (the archive after merge would fail). Shorten it: move examples and "
                        "edge cases into scenarios."
                    )
    for p in problems:
        print(f"::error::{p}", flush=True)
    if not problems:
        print(f"Every ADDED and MODIFIED requirement in the active changes is {MAX} characters or fewer.")
    return problems


if __name__ == "__main__":
    if sys.argv[1:]:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(1 if check() else 0)
