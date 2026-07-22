from __future__ import annotations

import ast


def matrix_shape_check(*, matrix) -> dict:
    value = ast.literal_eval(matrix) if isinstance(matrix, str) else matrix
    if not isinstance(value, (list, tuple)) or not value:
        return _result("fail", "hard", "matrix must contain rows", {})
    rows = list(value)
    if any(not isinstance(row, (list, tuple)) for row in rows):
        return _result("fail", "hard", "matrix rows are malformed", {})
    widths = {len(row) for row in rows}
    if len(widths) != 1 or 0 in widths:
        return _result("fail", "hard", "matrix is not rectangular", {})
    return _result("pass", "hard", "matrix has a rectangular shape", {"shape": [len(rows), widths.pop()]})


def _result(status: str, strength: str, summary: str, payload: dict) -> dict:
    return {"status": status, "strength": strength, "summary": summary, "payload": payload}
