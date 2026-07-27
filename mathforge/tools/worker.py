from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib
import json
import os
import sys
from typing import Any

from mathforge.tools.registry import ToolRegistry, run_tool_direct
from mathforge.tools.resource_limits import (
    MAX_WORKER_REQUEST_BYTES,
    MAX_WORKER_RESPONSE_BYTES,
    WORKER_ADDRESS_SPACE_BYTES,
    WORKER_CPU_SECONDS,
    inspect_tool_arguments,
)


def main(*, apply_limits: bool = True) -> int:
    if apply_limits:
        _apply_resource_limits()
    try:
        request_bytes = sys.stdin.buffer.read(MAX_WORKER_REQUEST_BYTES + 1)
        if len(request_bytes) > MAX_WORKER_REQUEST_BYTES:
            return _write(_failure("isolated tool request exceeded limit"))
        request = json.loads(request_bytes.decode("utf-8"))
        name = str(request["name"])
        arguments = dict(request.get("arguments", {}))
        definition = ToolRegistry().get(name)
        if not definition.isolated:
            return _write(_failure("tool is not approved for isolated execution"))
        inspect_tool_arguments(arguments)
        with open(os.devnull, "w", encoding="utf-8") as null:
            with redirect_stdout(null), redirect_stderr(null):
                payload = run_tool_direct(name, arguments).to_dict()
        return _write(payload)
    except Exception:
        return _write(_failure("isolated tool failed"))


def _write(payload: dict[str, Any]) -> int:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_WORKER_RESPONSE_BYTES:
        encoded = json.dumps(
            _failure("isolated tool response exceeded limit"),
            separators=(",", ":"),
        ).encode("utf-8")
    sys.stdout.buffer.write(encoded)
    return 0


def _failure(summary: str) -> dict[str, Any]:
    return {
        "status": "error",
        "strength": "soft",
        "summary": summary,
        "payload": {},
    }


def _apply_resource_limits() -> None:
    if hasattr(sys, "set_int_max_str_digits"):
        sys.set_int_max_str_digits(640)
    try:
        resource = importlib.import_module("resource")
    except ImportError:
        return
    resource.setrlimit(
        resource.RLIMIT_CPU,
        (WORKER_CPU_SECONDS, WORKER_CPU_SECONDS),
    )
    resource.setrlimit(
        resource.RLIMIT_AS,
        (WORKER_ADDRESS_SPACE_BYTES, WORKER_ADDRESS_SPACE_BYTES),
    )
    resource.setrlimit(
        resource.RLIMIT_FSIZE,
        (MAX_WORKER_RESPONSE_BYTES, MAX_WORKER_RESPONSE_BYTES),
    )


if __name__ == "__main__":
    raise SystemExit(main())
