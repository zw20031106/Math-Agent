"""Trustworthy offline evaluation helpers."""

from mathforge.evaluation.evidence_baseline import (
    aggregate_local_final_corpus,
    extract_local_final_corpus,
    parse_official_evaluation_log,
)
from mathforge.evaluation.prompt_contract_probe import (
    PROMPT_CONTRACT_PROBE_CASES,
    PromptContractProbeReport,
    assess_prompt_contract_responses,
    run_live_prompt_contract_probe,
)
from mathforge.evaluation.scoring import ScoreResult, score_response
from mathforge.evaluation.artifacts import (
    COMPETITION_OUTER_SECONDS,
    COMPETITION_TIMING_PROFILE,
    CurrentRunIdentity,
    DEBUG_NONCOMPARABLE_TIMING_PROFILE,
    RunIdentity,
    build_run_identity,
    can_register_baseline,
    ensure_competition_timing,
    run_identity_errors,
    timing_profile_for,
    validate_baseline_artifact,
    validate_current_run_identity,
)
from mathforge.evaluation.failure_attribution import (
    FAILURE_CAUSES,
    PRIMARY_FAILURE_CAUSES,
    FailureAttribution,
    aggregate_failure_attribution,
    attribute_case_failure,
    attribute_failure,
    classify_failure,
    validate_failure_attributions,
)
from mathforge.evaluation.evidence_registry import (
    baseline_registration_errors,
    can_register_baseline as can_register_registry_baseline,
)

__all__ = [
    "PROMPT_CONTRACT_PROBE_CASES",
    "PromptContractProbeReport",
    "ScoreResult",
    "aggregate_local_final_corpus",
    "assess_prompt_contract_responses",
    "extract_local_final_corpus",
    "parse_official_evaluation_log",
    "run_live_prompt_contract_probe",
    "score_response",
    "COMPETITION_OUTER_SECONDS",
    "COMPETITION_TIMING_PROFILE",
    "CurrentRunIdentity",
    "DEBUG_NONCOMPARABLE_TIMING_PROFILE",
    "RunIdentity",
    "build_run_identity",
    "can_register_baseline",
    "ensure_competition_timing",
    "run_identity_errors",
    "timing_profile_for",
    "validate_baseline_artifact",
    "validate_current_run_identity",
    "FAILURE_CAUSES",
    "PRIMARY_FAILURE_CAUSES",
    "FailureAttribution",
    "aggregate_failure_attribution",
    "attribute_case_failure",
    "attribute_failure",
    "classify_failure",
    "validate_failure_attributions",
    "baseline_registration_errors",
    "can_register_registry_baseline",
]
from mathforge.evaluation.production_preflight import run_production_preflight

__all__ = ["run_production_preflight"]
