from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

import mathforge.provenance as provenance_module
import mathforge.runtime as runtime_module
from mathforge.config import HarnessConfig, load_competition_config
from mathforge.harness.schemas import CandidateSolution, Claim
from mathforge.harness.stages import (
    CandidateStage,
    ContextRouteStage,
    EvidenceStage,
    ProofStage,
)
from mathforge.output.answer_validator import AnswerValidator
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.tools.executor import ToolExecutor
from mathforge.verification.admission import CandidateAdmissionGate
from mathforge.verification.evidence import EvidenceLedger
from scripts.scan_secrets import scan_repository
from scripts.run_case_outputs import _contained_case_path
from scripts.verify_baseline_files import MANIFEST, verify
from scripts.verify_build_provenance import verify as verify_build_provenance
from tests.fake_client import FakeClient
from tests.test_runtime_state import _minimal_config


ROOT = Path(__file__).resolve().parents[1]


def _candidate(identifier: str = "candidate-1") -> CandidateSolution:
    return CandidateSolution(
        candidate_id=identifier,
        role="PrimarySolver",
        method="direct-deduction",
        final_answer="2",
        answer_type="integer",
        claims=[Claim("c1", "1+1=2")],
        public_solution_steps=["Evaluate the sum."],
        solution_text="Evaluate 1+1 to obtain 2.",
    )


def test_typed_stages_preserve_candidate_evidence_and_proof_contracts():
    problem = ProblemParser().parse("Calculate the integer 1+1.")
    candidate = _candidate()
    candidate.answer_type = problem.answer_type
    candidate_stage = CandidateStage(CandidateAdmissionGate(AnswerValidator()))
    evidence_stage = EvidenceStage(ToolExecutor())
    proof_stage = ProofStage()
    ledger = EvidenceLedger([], candidates=[candidate])

    admission = candidate_stage.evaluate(candidate, problem)
    evidence_gate = evidence_stage.hard_gate([candidate], ledger, enabled=True)
    obligations = proof_stage.generate(problem, candidate)
    completion = proof_stage.evaluate(candidate, ledger.records, obligations)

    assert admission.accepted
    assert evidence_gate.accepted == [candidate]
    assert evidence_gate.rejected_candidate_ids == []
    assert completion.candidate_id == candidate.candidate_id


def test_disabled_components_are_not_constructed_and_formal_init_does_not_run_git(
    monkeypatch,
):
    def forbidden(*args, **kwargs):
        del args, kwargs
        raise AssertionError("disabled or heavyweight constructor was called")

    provenance_module._default_static_provenance.cache_clear()
    monkeypatch.setattr(runtime_module, "Retriever", forbidden)
    monkeypatch.setattr(runtime_module, "LLMFinalizer", forbidden)
    monkeypatch.setattr(provenance_module.subprocess, "run", forbidden)

    harness = runtime_module.MathForgeHarness(FakeClient(), _minimal_config())

    assert harness._retriever is None
    assert harness._finalizer is None
    assert isinstance(harness._candidate_stage, CandidateStage)
    assert isinstance(harness._context_route_stage, ContextRouteStage)
    assert isinstance(harness._evidence_stage, EvidenceStage)
    assert isinstance(harness._proof_stage, ProofStage)


def test_competition_config_is_fully_expanded_and_has_no_environment_overlay():
    competition = load_competition_config()
    payload = json.loads(
        (ROOT / "config" / "competition.json").read_text(encoding="utf-8")
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    sources = (ROOT / "docs" / "CONFIGURATION_SOURCES.md").read_text(
        encoding="utf-8"
    )

    assert set(payload) == {
        "schema_version",
        "profile",
        "status",
        *HarnessConfig.setting_names(),
    }
    assert competition.to_dict() == payload
    assert not hasattr(HarnessConfig, "from_environment")
    assert "loads exactly `config/competition.json`" in readme
    assert "single source of truth" in sources
    assert "There are no environment" in sources


def test_baseline_manifest_groups_immutable_and_participant_files():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "2.0"
    assert set(manifest["official_immutable"]) == {"main.py", "llm_client.py"}
    assert manifest["participant_mutable"] == ["user_agent.py"]
    assert verify() == []


def test_secret_scan_covers_token_forms_high_entropy_and_digest_allowlist(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "secret_scan_allowlist.json").write_text(
        '{"schema_version":"1.0","entries":[]}',
        encoding="utf-8",
    )
    token = "s" + "k-" + "A1" * 16
    bearer = "Bearer " + "zY8_" * 10
    intern = "INTERN_TOKEN=" + "Q7w_" * 10
    assignment = "api_key=" + "R5v_" * 10
    entropy = (
        "Aa0+Bb1/Cc2="
        + "Dd3_Ee4-Ff5+"
        + "Gg6/Hh7=Ii8_"
        + "Jj9-Kk0+Ll1/"
        + "Mm2=Nn3_Oo4-"
    )
    secret_file = tmp_path / "secrets.txt"
    secret_file.write_text(
        "\n".join((token, bearer, intern, assignment, f'"{entropy}"')),
        encoding="utf-8",
    )

    findings = scan_repository(tmp_path)
    assert {
        "api_token",
        "bearer_token",
        "intern_token",
        "api_key_assignment",
        "high_entropy_string",
    } <= {finding.kind for finding in findings}

    digest = sha256(token[3:].encode("utf-8")).hexdigest()
    (tmp_path / "config" / "secret_scan_allowlist.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "entries": [
                    {
                        "path": "secrets.txt",
                        "kind": "api_token",
                        "value_sha256": digest,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert "api_token" not in {
        finding.kind for finding in scan_repository(tmp_path)
    }


def test_pep621_declares_python310_project_and_bundled_runtime_resources():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'requires = ["setuptools==82.0.1"]' in project
    assert "[project]" in project
    assert 'requires-python = ">=3.10"' in project
    assert '"requests>=2.31,<3"' in project
    assert '"sympy>=1.12,<2"' in project
    assert 'py-modules = ["user_agent"]' in project
    for destination in (
        "share/mathforge/config",
        "share/mathforge/data",
        "share/mathforge/docs",
        "share/mathforge/prompts/primary_solver",
        "share/mathforge/skills/domains",
        "share/mathforge/skills/general",
    ):
        assert f'"{destination}"' in project
    assert (ROOT / "constraints-py310-linux.txt").is_file()
    assert verify_build_provenance() == []


def test_documented_runner_boundaries_match_the_safe_runner_contract():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "formal platform entry is `user_agent.py`" in readme
    assert "rolling case window with default and maximum" in readme
    assert "concurrency four" in readme
    assert "immutable legacy baseline fixtures" in readme


def test_safe_runner_resolves_every_case_path_inside_output_directory(tmp_path):
    destination = _contained_case_path(tmp_path, "case-01")

    assert destination.parent == tmp_path.resolve()
    assert destination.name == "case-01.json"
    with pytest.raises(ValueError, match="safe for a filename"):
        _contained_case_path(tmp_path, "../escape")
