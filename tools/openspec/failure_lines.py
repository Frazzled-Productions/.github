#!/usr/bin/env python3
"""Pick the real error lines out of the archive bot's log, for report-failure.sh.

  failure_lines.py text <log>                 the error lines, as plain text (for the issue)
  failure_lines.py annotations <log> <why>    `::error::` lines: the reason, then one per error

The error lines are each "PROBLEM: " block archive.py printed (the line and the ones after it, up to
the next "PROBLEM: " line, the next "$ " command echo or the end), or, when there is none (a gh or
git failure, or the stuck job's check list), the last 20 lines of the log. Lines starting "✓ " are
passing items and are dropped.

Each annotation is a single line: "%", CR and LF are encoded (%25, %0D, %0A) as GitHub's workflow
commands expect, so no text from the log can start a workflow command of its own.
"""
import sys

TAIL = 20
MAX_BLOCKS = 9  # GitHub shows at most 10 error annotations per step; one is the reason
MAX_LINES = 60
MAX_CHARS = 4000


def blocks(text):
    lines = [line for line in text.splitlines() if not line.startswith("✓ ")]
    found, current = [], None
    for line in lines:
        if line.startswith("PROBLEM: "):
            if current:
                found.append(current)
            current = [line]
        elif current is not None:
            if line.startswith("$ "):
                found.append(current)
                current = None
            else:
                current.append(line)
    if current:
        found.append(current)
    found = [trim(b) for b in found if trim(b)]
    if not found:
        tail = trim(lines)[-TAIL:]
        found = [tail] if tail else [["(the log is empty)"]]
    return [cut(b) for b in found[:MAX_BLOCKS]]


def trim(lines):
    lines = list(lines)
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    return lines


def cut(lines):
    text = "\n".join(lines[:MAX_LINES])
    if len(lines) > MAX_LINES or len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n(cut short; the full output is in the issue)"
    return text


def encode(text):
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(argv):
    if len(argv) == 2 and argv[0] == "text":
        print("\n\n".join(blocks(read(argv[1]))))
        return 0
    if len(argv) == 3 and argv[0] == "annotations":
        print("::error::" + encode(argv[2]))
        for block in blocks(read(argv[1])):
            print("::error::" + encode(block))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
