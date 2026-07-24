from __future__ import annotations

import pytest

from mathforge.model_identity import EXACT_INTERN_MODEL, MODEL_ENVIRONMENT_VARIABLE


@pytest.fixture(autouse=True)
def exact_competition_model_environment(monkeypatch):
    monkeypatch.setenv(MODEL_ENVIRONMENT_VARIABLE, EXACT_INTERN_MODEL)
