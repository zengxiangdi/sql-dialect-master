"""Scanner-backed function-call replacement shared by custom SQL rewrites."""
from __future__ import annotations

import re
from typing import Callable

from .p1_sql_scanner import mask_non_executable


def replace_function_calls(
    sql: str,
    function_name: str,
    replacer: Callable[[str, str], str],
) -> str:
    """Replace complete calls without interpreting literals or comments as SQL."""
    upper_name = function_name.upper()
    name_len = len(function_name)
    masked = mask_non_executable(sql)
    result = []
    i = 0
    length = len(sql)

    while i < length:
        if masked[i:i + name_len].upper() != upper_name:
            result.append(sql[i])
            i += 1
            continue

        name_end = i + name_len
        if i > 0 and (masked[i - 1].isalnum() or masked[i - 1] == "_"):
            result.append(sql[i])
            i += 1
            continue

        j = name_end
        while j < length and masked[j].isspace():
            j += 1
        if j >= length or masked[j] != "(":
            result.append(sql[i])
            i += 1
            continue

        depth = 0
        k = j
        while k < length:
            char = masked[k]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    original_call = sql[i:k + 1]
                    args = sql[j + 1:k]
                    result.append(replacer(args, original_call))
                    i = k + 1
                    break
            k += 1
        else:
            result.append(sql[i:])
            break

    return "".join(result)


__all__ = ["replace_function_calls"]
