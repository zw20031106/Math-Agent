from __future__ import annotations

from scripts.check_coverage_gates import MODULE_BRANCH_GATES


def test_s4_critical_module_coverage_gates_are_explicit():
    assert MODULE_BRANCH_GATES == {
        "mathforge/runtime.py": 80.0,
        "mathforge/tools/symbolic.py": 80.0,
        "mathforge/tools/numerical.py": 80.0,
        "mathforge/tools/worker.py": 80.0,
        "user_agent.py": 90.0,
        "mathforge/verification/completion.py": 90.0,
        "mathforge/harness/terminalizer.py": 90.0,
        "mathforge/verification/evidence.py": 85.0,
        "mathforge/config.py": 70.0,
        "mathforge/output/deterministic_formatter.py": 70.0,
    }
