"""Small lexical scanner for SQL rewrites that must avoid literals/comments."""
from __future__ import annotations

from typing import Iterator, Tuple


def executable_segments(sql: str) -> Iterator[Tuple[int, int]]:
    """Yield [start, end) ranges outside strings, quoted identifiers and comments."""
    i = 0
    start = 0
    n = len(sql)
    state = "code"
    dollar_tag = None
    while i < n:
        if state == "code":
            if sql.startswith("--", i):
                if start < i:
                    yield start, i
                state = "line_comment"
                i += 2
                start = i
                continue
            if sql.startswith("/*", i):
                if start < i:
                    yield start, i
                state = "block_comment"
                i += 2
                start = i
                continue
            ch = sql[i]
            if ch == "q" or ch == "Q":
                if i + 2 < n and sql[i + 1] == "'":
                    opener = sql[i + 2]
                    closer = {"[": "]", "{": "}", "(": ")", "<": ">"}.get(opener, opener)
                    delimiter = f"{closer}'"
                    end = sql.find(delimiter, i + 3)
                    if end != -1:
                        if start < i:
                            yield start, i
                        i = end + len(delimiter)
                        start = i
                        continue
            if ch == "'":
                if start < i:
                    yield start, i
                state = "single_quote"
                i += 1
                start = i
                continue
            if ch == '"':
                if start < i:
                    yield start, i
                state = "double_quote"
                i += 1
                start = i
                continue
            if ch == '`':
                if start < i:
                    yield start, i
                state = "backtick_quote"
                i += 1
                start = i
                continue
            if ch == '[':
                if start < i:
                    yield start, i
                state = "bracket_quote"
                i += 1
                start = i
                continue
            if ch == "$":
                j = sql.find("$", i + 1)
                if j != -1 and (sql[i + 1:j].replace("_", "").isalnum() or j == i + 1):
                    if start < i:
                        yield start, i
                    dollar_tag = sql[i:j + 1]
                    state = "dollar_quote"
                    i = j + 1
                    start = i
                    continue
            i += 1
            continue
        if state == "single_quote":
            if sql[i:i + 2] == "''":
                i += 2
                continue
            if sql[i] == "\\" and i + 1 < n:
                i += 2
                continue
            if sql[i] == "'":
                state = "code"
                i += 1
                start = i
                continue
            i += 1
            continue
        if state == "double_quote":
            if sql[i:i + 2] == '""':
                i += 2
                continue
            if sql[i] == '"':
                state = "code"
                i += 1
                start = i
                continue
            i += 1
            continue
        if state == "backtick_quote":
            if sql[i:i + 2] == "``":
                i += 2
                continue
            if sql[i] == '`':
                state = "code"
                i += 1
                start = i
                continue
            i += 1
            continue
        if state == "bracket_quote":
            if sql[i:i + 2] == "]]":
                i += 2
                continue
            if sql[i] == ']':
                state = "code"
                i += 1
                start = i
                continue
            i += 1
            continue
        if state == "line_comment":
            if sql[i] in "\r\n":
                state = "code"
                start = i
            i += 1
            continue
        if state == "block_comment":
            if sql.startswith("*/", i):
                state = "code"
                i += 2
                start = i
            else:
                i += 1
            continue
        if state == "dollar_quote":
            if dollar_tag is None:
                return
            end = sql.find(dollar_tag, i)
            if end == -1:
                return
            state = "code"
            i = end + len(dollar_tag)
            start = i
    if state == "code" and start < n:
        yield start, n


def mask_non_executable(sql: str) -> str:
    """Replace non-code characters with spaces while preserving positions."""
    masked = list(sql)
    for start, end in _non_executable_ranges(sql):
        for i in range(start, end):
            masked[i] = " "
    return "".join(masked)


def _non_executable_ranges(sql: str):
    covered = []
    cursor = 0
    for start, end in executable_segments(sql):
        if cursor < start:
            covered.append((cursor, start))
        cursor = end
    if cursor < len(sql):
        covered.append((cursor, len(sql)))
    return covered
