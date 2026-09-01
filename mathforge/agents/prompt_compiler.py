from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from math import floor
from typing import Mapping

from mathforge.agent_runtime.action_registry import ActionRegistry
from mathforge.agent_runtime.protocol import (
    AGENT_TURN_FIELDS,
    LITE_AGENT_TURN_FIELDS,
    LITE_PROTOCOL_SCHEMA_VERSION,
    PROTOCOL_SCHEMA_VERSION,
)
from mathforge.agent_runtime.router_protocol import (
    ROUTER_INTENT_FIELDS,
    ROUTER_INTENT_STRUCTURAL_SHAPE,
)
from mathforge.agents.registry import PromptContract, PromptContractLoader
from mathforge.context.errors import ContextBudgetExceeded
from mathforge.harness.context_budget import InternS2TokenCounter
from mathforge.harness.model_candidate_contract import (
    MODEL_CANDIDATE_PATCH_FIELDS,
    MODEL_CANDIDATE_PATCH_STRUCTURAL_SHAPE,
    MODEL_CANDIDATE_PROFILE_FIELDS,
    candidate_profile_example,
    candidate_profile_for_response_mode,
    candidate_profile_shape,
    model_semantic_payload_example,
    MODEL_SEMANTIC_REQUIRED_FIELDS,
)
from mathforge.harness.model_policy import stage_output_cap
from mathforge.harness.schemas import (
    ProblemIR,
    RoutePlan,
    strip_prompt_descriptions,
)


# Stage-owned state slices.  The names are the public JSON keys emitted by
# RoleContextView/ReasoningState; keeping this table immutable makes the
# compiler the single authority for what a role may see.  A stage can still
# receive the problem and its declared protocol fields, but never an
# accidental full session snapshot.
REQUIRED_STATE_FIELDS: Mapping[str, tuple[str, ...]] = {
    "router_planner": (
        "context_snapshot_id",
        "conditions",
        "final_answer",
        "metadata",
    ),
    "primary_solver": (
        "context_snapshot_id",
        "conditions",
        "final_answer",
        "candidates",
        "evidence",
        "obligations",
        "claim_graph",
        "metadata",
    ),
    "alternative_solver": (
        "context_snapshot_id",
        "conditions",
        "final_answer",
        "candidates",
        "evidence",
        "obligations",
        "claim_graph",
        "metadata",
    ),
    "lemma_curator": (
        "context_snapshot_id",
        "conditions",
        "evidence",
        "obligations",
        "claim_graph",
        "metadata",
    ),
    "verifier_skeptic": (
        "context_snapshot_id",
        "conditions",
        "final_answer",
        "candidates",
        "evidence",
        "obligations",
        "claim_graph",
        "metadata",
    ),
    "repair": (
        "context_snapshot_id",
        "conditions",
        "candidates",
        "evidence",
        "obligations",
        "claim_graph",
        "metadata",
    ),
    "finalizer": (
        "context_snapshot_id",
        "final_answer",
        "candidates",
        "evidence",
        "obligations",
        "claim_graph",
        "metadata",
    ),
}

# A ReasoningState has more lifecycle metadata than a model needs.  These
# fields preserve the ProblemFrame, current public frontier, obligations and
# hard-evidence/backbone links required for a sound continuation.
REQUIRED_REASONING_FIELDS: tuple[str, ...] = (
    "state_id",
    "version",
    "problem_frame",
    "subgoal_ledger",
    "claim_ledger",
    "open_obligations",
    "evidence_refs",
    "contradictions",
    "strategy",
    "verified_fact_bank",
    "proof_backbone",
)
_STATE_SECTION_MARKERS = (
    "Authorized context view:",
    "Authorized finalizer context:",
    "Authorized repair context:",
    "Public ReasoningState JSON:",
)
_ROLE_DIRECTORY_TO_STAGE = {
    "router_planner": "router",
    "primary_solver": "primary",
    "alternative_solver": "alternative",
    "lemma_curator": "lemma",
    "verifier_skeptic": "verifier",
    "repair": "repair",
    "finalizer": "finalizer",
}
_ROLE_DIRECTORY_TO_ROLE = {
    "router_planner": "RouterPlanner",
    "primary_solver": "PrimarySolver",
    "alternative_solver": "AlternativeSolver",
    "lemma_curator": "LemmaCurator",
    "verifier_skeptic": "VerifierSkeptic",
    "repair": "RepairAgent",
    "finalizer": "LLMFinalizer",
}
_CHINESE_LANGUAGE_DIRECTIVE = (
    "自然语言用中文；公式、LaTeX、JSON 字段名和协议标识保持原样；只返回指定 JSON。"
)
_ACTION_REGISTRY = ActionRegistry()
_SOLVER_OUTPUT_TOKENS = {
    "minimal": {
        "primary_solver": 2048,
        "alternative_solver": 2048,
    },
    "standard": {
        "primary_solver": 32768,
        "alternative_solver": 32768,
    },
    "tool": {
        "primary_solver": 32768,
        "alternative_solver": 32768,
    },
    "proof": {
        "primary_solver": 40960,
        "alternative_solver": 40960,
    },
}
_AGENT_TURN_ENVELOPE_PROTOCOL = (
    "AgentTurnPayload 1.0（公共协议模式）。仅返回一个裸 JSON 对象，外层字段按序为 "
    "protocol_version, task_result_type, action, public_state_delta, result_payload, "
    "outbound_intents, progress_summary, stop_reason；protocol_version=\"1.0\"。"
    "Host 负责所有 ID、版本、状态、限额和超时，模型不得生成。"
)
_AGENT_TURN_LITE_ENVELOPE_PROTOCOL = (
    "AgentTurnPayload 1.1-lite（精简公共协议）。仅返回裸 JSON，字段为 action, payload, "
    "outbound, stop_reason。Host 负责协议版本、类型、ID、版本、状态、优先级、限额、"
    "超时和摘要，模型不得生成。"
)


def _agent_turn_candidate_example(profile: str) -> dict[str, object]:
    return {
        "protocol_version": "1.0",
        "task_result_type": "CandidateArtifact",
        "action": "publish_candidate",
        "public_state_delta": {},
        "result_payload": candidate_profile_example(profile),
        "outbound_intents": [],
        "progress_summary": "<public completion summary>",
        "stop_reason": "candidate_complete",
    }


def _candidate_profile_protocol(
    profile: str,
    *,
    autonomous: bool,
    protocol_variant: str = PROTOCOL_SCHEMA_VERSION,
    semantic_payload: bool = False,
) -> str:
    normalized = candidate_profile_for_response_mode(profile)
    lite = protocol_variant == LITE_PROTOCOL_SCHEMA_VERSION
    if protocol_variant not in {PROTOCOL_SCHEMA_VERSION, LITE_PROTOCOL_SCHEMA_VERSION}:
        raise ValueError("unsupported AgentTurnPayload protocol version")
    use_semantic = bool(semantic_payload or lite)
    shape = (
        json.dumps(
            (
                {
                    "action": "publish_candidate",
                    "payload": model_semantic_payload_example(normalized),
                    "outbound": [],
                    "stop_reason": "candidate_complete",
                }
                if lite
                else {
                    "protocol_version": "1.0",
                    "task_result_type": "CandidateArtifact",
                    "action": "publish_candidate",
                    "public_state_delta": {},
                    "result_payload": (
                        model_semantic_payload_example(normalized)
                        if use_semantic
                        else candidate_profile_example(normalized)
                    ),
                    "outbound_intents": [],
                    "progress_summary": "<public completion summary>",
                    "stop_reason": "candidate_complete",
                }
            ),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if autonomous or lite
        else (
            json.dumps(
                model_semantic_payload_example(normalized),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if use_semantic
            else candidate_profile_shape(normalized)
        )
    )
    profile_instruction = {
        "answer_only": (
            "result_payload 仅含 final_answer 和一个含 statement、claim_kind 的检查。"
        ),
        "worked_solution": (
            "result_payload 含 final_answer、method、语义 steps 和 uncertainties。"
        ),
        "proof_full": (
            "result_payload 含 final_answer、method、至少两步完整 proof_steps 和 open_conditions。"
        ),
    }[normalized]
    envelope = (
        _AGENT_TURN_LITE_ENVELOPE_PROTOCOL
        if lite
        else _AGENT_TURN_ENVELOPE_PROTOCOL
        if autonomous
        else "Return one bare Candidate response object only（仅返回 Candidate JSON）。"
    )
    if use_semantic:
        profile_instruction = {
            "answer_only": (
                "payload 仅含 final_answer、solution_text；solution_text 是简短公共检查。"
            ),
            "worked_solution": (
                "payload 含 final_answer、solution_text；仅在验证需要时加入 method 或结构化 Claims。"
            ),
            "proof_full": (
                "payload 含 final_answer、solution_text、有序 proof_steps，必要时含 critical_claims 和 open_conditions。"
            ),
        }[normalized]
    return (
        envelope
        + f"Candidate response mode is {normalized}；{profile_instruction} "
        + (
            "只给数学语义字段，payload 保持最小。"
            if use_semantic
            else "语义步骤只含 statement、claim_kind、depends_on（此前步骤的零基索引）。"
        )
        + "Host 分配生命周期 ID；final_answer 无标签，LaTeX 反斜杠按 JSON 转义。"
        f"Exact JSON schema example: {shape}."
    )


_PROGRESS_DELTA_FIELDS = (
    "claims",
    "closed_obligation_ids",
    "contradictions",
    "next_step",
    "open_obligations",
    "public_summary",
    "stop_reason",
    "strategy",
    "subgoals",
)


def _progress_delta_example() -> dict[str, object]:
    return {
        "public_summary": "<public progress>",
        "strategy": "<current method>",
        "subgoals": [
            {
                "statement": "<public target>",
                "depends_on": [],
                "exit_condition": "<observable closure>",
            }
        ],
        "claims": [
            {
                "statement": "<atomic public claim>",
                "claim_kind": "reasoning",
                "depends_on": [],
                "subgoal_refs": [0],
                "importance": "supporting",
            }
        ],
        "open_obligations": [],
        "closed_obligation_ids": [],
        "contradictions": [],
        "next_step": "<one bounded action>",
        "stop_reason": "",
    }


def _progress_delta_protocol(
    mode: str,
    *,
    autonomous: bool,
    role: str = "PrimarySolver",
    protocol_variant: str = PROTOCOL_SCHEMA_VERSION,
) -> str:
    if protocol_variant not in {PROTOCOL_SCHEMA_VERSION, LITE_PROTOCOL_SCHEMA_VERSION}:
        raise ValueError("unsupported AgentTurnPayload protocol version")
    delta = _progress_delta_example()
    example: dict[str, object]
    if autonomous and protocol_variant == LITE_PROTOCOL_SCHEMA_VERSION:
        example = {
            "action": "continue_reasoning",
            "payload": delta,
            "outbound": [],
            "stop_reason": "",
        }
    elif autonomous:
        example = {
            "protocol_version": "1.0",
            "task_result_type": "ProgressArtifact",
            "action": "continue_reasoning",
            "public_state_delta": delta,
            "result_payload": {},
            "outbound_intents": [],
            "progress_summary": "<public progress summary>",
            "stop_reason": "",
        }
    else:
        example = delta
    action_enum = ", ".join(
        _ACTION_REGISTRY.prompt_actions(role, phase="progress")
    )
    if autonomous and protocol_variant == LITE_PROTOCOL_SCHEMA_VERSION:
        envelope = _AGENT_TURN_LITE_ENVELOPE_PROTOCOL
        fields = "action, payload, outbound, stop_reason"
    else:
        envelope = _AGENT_TURN_ENVELOPE_PROTOCOL if autonomous else "Return one bare JSON object. "
        fields = (
            "public_summary, strategy, subgoals, claims, open_obligations, "
            "closed_obligation_ids, contradictions, next_step, stop_reason"
        )
    field_clause = (
        "these nine fields and no others: public_summary, strategy, subgoals, "
        "claims, open_obligations, closed_obligation_ids, contradictions, "
        "next_step, stop_reason"
        if protocol_variant == PROTOCOL_SCHEMA_VERSION
        else f"these fields and no others: {fields}"
    )
    return (
    f"Public protocol mode is {mode}。构造一个可审计 ProgressDelta，字段为 {field_clause}。"
    "这是公共进展，不是最终 Candidate；字符串字段保持字符串，subgoals/claims 使用约定结构。"
    "依赖和 subgoal_refs 使用此前项目的零基索引；已有 ID 只能引用。Host 分配新 ID、状态、版本、"
    "来源、分支和检查规范；closed_obligation_ids 只能引用已有义务。只写原子、可公开检查的数学。"
    "不得输出最终答案、CandidateSolution、工具调用、原始回复或 Host 生命周期字段。"
    + (
        f"本回合允许的 ActionRegistry 动作为：{action_enum}。"
        if autonomous
        else ""
    )
    + envelope
    + "Exact JSON schema example: "
    + json.dumps(example, ensure_ascii=False, separators=(",", ":"))
    + "."
    )
_PEER_REVIEW_PROTOCOL = (
    _AGENT_TURN_ENVELOPE_PROTOCOL
    + "Public protocol mode is peer_review。使用 task_result_type=PeerReviewArtifact、"
    "action=challenge_candidate；result_payload 只含 finding_items、answer_assessment、"
    "method_overlap_assessment、missing_conditions、counterexample_attempts、"
    "unresolved_obligations、recommended_action、stop_reason。每个 finding_item 必须引用"
    "真实 candidate_id/claim_id，status 为 pass/fail/unknown，severity 为 info/warning/error/critical。"
    "public_state_delta={}、outbound_intents=[]；只评审，不重写 Candidate。"
)
_REBUTTAL_PROTOCOL = (
    _AGENT_TURN_ENVELOPE_PROTOCOL
    + "Public protocol mode is respond_to_review。使用 RebuttalArtifact/publish_rebuttal；"
    "result_payload 只含非空 responses 和 stop_reason。每项含 finding_id、response、action、"
    "supporting_claim_ids、evidence_refs、requested_followup；仅引用已提供的 Finding/Claim。"
    "action 为 defend/clarify/concede，concede 必须明确；不得静默修复 Candidate。"
)
_CROSS_EXAM_PROTOCOL = (
    _AGENT_TURN_ENVELOPE_PROTOCOL
    + "Public protocol mode is cross_exam。使用 CritiqueArtifact/challenge_candidate；"
    "result_payload 只含 findings、peer_review_assessments、uncovered_goal_ids、"
    "recommended_action、stop_reason。Finding 必须引用真实 Claim/义务，标明 status、scope、"
    "actionability 和公共理由；逐项评估已提供的 Peer Finding。局部失败不得改报全局修复；"
    "不修复、不求解、不仲裁。"
)
_FINAL_AUDIT_PROTOCOL = (
    _AGENT_TURN_ENVELOPE_PROTOCOL
    + "Public protocol mode is final_audit。使用 AuditArtifact/complete；result_payload 只含 "
    "candidate_id、candidate_version、status、open_finding_ids、open_obligation_ids、"
    "reviewed_artifact_ids、reviewed_finding_ids、reviewed_obligation_ids、requested_action、"
    "public_rationale、stop_reason。仅引用已提供的最终 Candidate 版本；完成状态必须覆盖全部审计项且"
    "无未闭 Finding/义务。只审计，不改写、润色、修复或生成答案。"
)
_REPAIR_PATCH_PROTOCOL = (
    "仅返回一个裸 JSON，含 replacement_claims、final_answer、public_solution_steps、"
    "unresolved_obligations。replacement_claims 只替换受影响 Claim，字段为 claim_id、statement、"
    "depends_on、check_type、importance；不得返回无关 Claim、method 或 Host 字段。Host 应用补丁后"
    "重验证依赖闭包并回滚退化。结构："
    f"{MODEL_CANDIDATE_PATCH_STRUCTURAL_SHAPE}。公式使用 $...$，final_answer 不加 $。"
)
_ROLE_PROTOCOLS = {
    "router_planner": (
        "仅返回 RouterIntent JSON。主机负责 subgoals（Host owns subgoals）、任务 DAG、角色分配、候选数、优先级、资源和版本。"
        f"严格使用该结构：{ROUTER_INTENT_STRUCTURAL_SHAPE}。"
    ),
    "lemma_curator": (
        _AGENT_TURN_ENVELOPE_PROTOCOL
        + "使用 task_result_type=LemmaArtifact、action=complete；result_payload 只有 lemmas。每个 lemma 含 "
        "statement、conditions、dependencies、proof_sketch、target_obligation_ids。Lemma 只是待验证目标，"
        "public_state_delta={}，progress_summary/stop_reason 非空，outbound_intents 只含 Host 指定的公开 recipient_role。"
        "不得求解或仲裁最终答案。"
    ),
    "verifier_skeptic": (
        "仅返回含 findings 的 JSON。每个 finding 含 candidate_id、claim_id、obligation_ids、review_target_ids、"
        "review_level、status、public_rationale、missing_condition、counterexample_summary；status 为 pass/fail/unknown。"
        "pass 必须引用真实 Claim 及已提供目标；只评审已提供的公开片段，不重构完整解答。"
    ),
    "repair": (
        f"{_REPAIR_PATCH_PROTOCOL} Change only the supplied failed Claim "
        "dependency closure；仅修复受影响闭包。除非终端 Claim 证明必须改变，否则保持 final_answer 不变。"
    ),
    "finalizer": (
        "仅返回含 final_answer、solution_text 两个字符串字段的裸 JSON，不得有其他字段。final_answer 使用无标签精确文本；"
        "只规范格式，保留 method、公开说明、已验证 Claims、假设、定理、未闭义务和原答案，不引入新数学内容。"
    ),
}


def _compact_json_object(raw: str, fields: tuple[str, ...]) -> tuple[str, bool]:
    """Slice the first JSON object in *raw* to the declared public fields."""

    leading = raw.lstrip()
    if not leading.startswith("{"):
        return raw, False
    try:
        payload, end = json.JSONDecoder().raw_decode(leading)
    except (TypeError, ValueError):
        return raw, False
    if not isinstance(payload, dict):
        return raw, False
    selected: dict[str, object] = {}
    for key in fields:
        if key not in payload:
            continue
        value = payload[key]
        if key == "metadata" and isinstance(value, dict):
            # Metadata is a declared transport channel, not permission to
            # expose compressor internals or authorized memory.  Preserve
            # only public benchmark/case metadata and the immutable problem
            # condition envelope used for interpretation.
            public_metadata = value.get("public_metadata")
            condition_envelope = value.get("problem_condition_envelope")
            value = {
                name: item
                for name, item in (
                    ("public_metadata", public_metadata),
                    ("problem_condition_envelope", condition_envelope),
                )
                if item not in (None, {}, [])
            }
        selected[key] = strip_prompt_descriptions(value)
    # Keep an explicitly empty object as a valid public state slice.  Do not
    # append arbitrary unknown keys: that would reintroduce full-state leaks.
    rendered = json.dumps(
        selected,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    prefix = raw[: len(raw) - len(leading)]
    suffix = leading[end:]
    return prefix + rendered + suffix, True


def _slice_marked_json(
    user_content: str,
    marker: str,
    fields: tuple[str, ...],
) -> tuple[str, bool]:
    """Replace the JSON payload immediately following a section marker."""

    start = user_content.find(marker)
    if start < 0:
        return user_content, False
    payload_start = start + len(marker)
    prefix = user_content[:payload_start]
    suffix = user_content[payload_start:]
    compacted, changed = _compact_json_object(suffix, fields)
    return prefix + compacted, changed


def _declared_state_slice(user_content: str, role_directory: str) -> tuple[str, bool]:
    """Apply role-specific context and ReasoningState field declarations."""

    context_fields = tuple(REQUIRED_STATE_FIELDS.get(role_directory, ()))
    result = user_content
    changed = False
    if context_fields:
        for marker in _STATE_SECTION_MARKERS[:3]:
            result, did_change = _slice_marked_json(result, marker, context_fields)
            changed = changed or did_change
    result, did_change = _slice_marked_json(
        result,
        _STATE_SECTION_MARKERS[3],
        REQUIRED_REASONING_FIELDS,
    )
    return result, changed or did_change


def _state_sections(user_content: str) -> str:
    """Return only marked state sections for component accounting."""

    starts = sorted(
        (user_content.find(marker), marker)
        for marker in _STATE_SECTION_MARKERS
        if user_content.find(marker) >= 0
    )
    if not starts:
        return ""
    parts: list[str] = []
    for index, (position, _marker) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(user_content)
        parts.append(user_content[position:end])
    return "\n".join(parts)


def _problem_section(user_content: str) -> str:
    """Extract the problem-bearing prefix, excluding skills and state."""

    text = user_content
    problem_index = text.find("Problem:")
    if problem_index >= 0:
        text = text[problem_index:]
    cut_markers = [
        position
        for marker in _STATE_SECTION_MARKERS
        for position in [text.find(marker)]
        if position >= 0
    ]
    skill_positions = [position for position in (text.find("# Skill:"),) if position >= 0]
    cuts = [*cut_markers, *skill_positions]
    if cuts:
        text = text[: min(cuts)]
    return text.strip()


def _trim_marked_state(user_content: str, max_tokens: int, counter: InternS2TokenCounter) -> str:
    """Deterministically trim state sections to a token allowance."""

    if max_tokens <= 0:
        starts = sorted(
            (user_content.find(marker), marker)
            for marker in _STATE_SECTION_MARKERS
            if user_content.find(marker) >= 0
        )
        if not starts:
            return user_content
        first = starts[0][0]
        return user_content[:first].rstrip()
    state = _state_sections(user_content)
    if not state or counter.count_text(state).tokens <= max_tokens:
        return user_content
    # Preserve only auditable identity metadata outside the dynamic state
    # sections.  This keeps context/benchmark correlation available to the
    # model and pollution probes while making the mathematical state share
    # gate independent of bookkeeping fields.
    starts = sorted(
        (user_content.find(marker), marker)
        for marker in _STATE_SECTION_MARKERS
        if user_content.find(marker) >= 0
    )
    first = starts[0][0]
    head = user_content[:first].rstrip()
    identity: dict[str, object] = {}
    for _position, marker in starts:
        suffix = user_content[_position + len(marker) :]
        leading = suffix.lstrip()
        if not leading.startswith("{"):
            continue
        try:
            payload, _end = json.JSONDecoder().raw_decode(leading)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        snapshot_id = payload.get("snapshot_id") or payload.get("context_snapshot_id")
        if snapshot_id and "context_snapshot_id" not in identity:
            identity["context_snapshot_id"] = str(snapshot_id)
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            public_metadata = metadata.get("public_metadata")
            if isinstance(public_metadata, dict):
                for key in ("benchmark_nonce", "case_id", "id", "idx"):
                    value = public_metadata.get(key)
                    if value is not None and key not in identity:
                        identity[key] = value
    identity_text = (
        "\n公开上下文标识：" + json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
        if identity
        else ""
    )
    return (
        head
        + identity_text
        + "\n状态已按阶段字段裁剪；仅保留问题与可验证结论。"
    )


@dataclass(frozen=True)
class PromptCompilation:
    profile: str
    messages: list[dict[str, str]]
    max_output_tokens: int
    prompt_chars: int
    output_schema_fields: tuple[str, ...] = ()
    output_schema_name: str = ""
    prompt_sha256: str = ""
    contract_sha256: str = ""
    role_directory: str = ""
    protocol_version: str = PROTOCOL_SCHEMA_VERSION
    contract_version: str = ""
    selected_skill_summary: str = ""
    prompt_tokens: int = 0
    prompt_counting_mode: str = ""
    tokenizer_revision: str = ""
    tokenizer_sha256: str = ""
    contract_tokens: int = 0
    runtime_protocol_tokens: int = 0
    skill_tokens: int = 0
    state_tokens: int = 0
    problem_tokens: int = 0
    schema_tokens: int = 0
    prompt_component_tokens: dict[str, int] = field(default_factory=dict)
    required_state_fields: tuple[str, ...] = ()
    state_slice_applied: bool = False
    state_trimmed: bool = False

    def snapshot(self) -> "CompiledPromptSnapshot":
        return CompiledPromptSnapshot.from_compilation(self)

    @property
    def prompt_hash(self) -> str:
        return self.prompt_sha256

    @property
    def max_output_cap(self) -> int:
        return self.max_output_tokens


@dataclass(frozen=True)
class CompiledPromptSnapshot:
    """Stable, answer-free metadata for a compiled Prompt contract.

    Golden snapshots intentionally contain hashes, schema metadata, and token
    accounting only; they never persist a problem answer or model transcript.
    """

    role_directory: str
    profile: str
    protocol_version: str
    contract_version: str
    contract_sha256: str
    prompt_sha256: str
    output_schema_name: str
    output_schema_fields: tuple[str, ...]
    selected_skill_summary: str
    max_output_cap: int
    prompt_tokens: int
    prompt_component_tokens: dict[str, int]
    required_state_fields: tuple[str, ...] = ()
    state_slice_applied: bool = False
    state_trimmed: bool = False

    @property
    def prompt_contract_version(self) -> str:
        return self.contract_version

    @property
    def prompt_hash(self) -> str:
        return self.prompt_sha256

    @property
    def max_output_tokens(self) -> int:
        return self.max_output_cap

    @property
    def output_schema(self) -> dict[str, object]:
        return {
            "name": self.output_schema_name,
            "fields": list(self.output_schema_fields),
        }

    @classmethod
    def from_compilation(cls, compilation: PromptCompilation) -> "CompiledPromptSnapshot":
        components = {
            name: max(0, int(value))
            for name, value in compilation.prompt_component_tokens.items()
        }
        return cls(
            role_directory=compilation.role_directory,
            profile=compilation.profile,
            protocol_version=compilation.protocol_version,
            contract_version=compilation.contract_version,
            contract_sha256=compilation.contract_sha256,
            prompt_sha256=compilation.prompt_sha256,
            output_schema_name=compilation.output_schema_name,
            output_schema_fields=tuple(compilation.output_schema_fields),
            selected_skill_summary=compilation.selected_skill_summary,
            max_output_cap=compilation.max_output_tokens,
            prompt_tokens=compilation.prompt_tokens,
            prompt_component_tokens=components,
            required_state_fields=tuple(compilation.required_state_fields),
            state_slice_applied=compilation.state_slice_applied,
            state_trimmed=compilation.state_trimmed,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "role_directory": self.role_directory,
            "profile": self.profile,
            "protocol_version": self.protocol_version,
            "contract_version": self.contract_version,
            "prompt_contract_version": self.contract_version,
            "contract_sha256": self.contract_sha256,
            "prompt_sha256": self.prompt_sha256,
            "prompt_hash": self.prompt_sha256,
            "output_schema_name": self.output_schema_name,
            "output_schema": {
                "name": self.output_schema_name,
                "fields": list(self.output_schema_fields),
            },
            "output_schema_fields": list(self.output_schema_fields),
            "selected_skill_summary": self.selected_skill_summary,
            "max_output_cap": self.max_output_cap,
            "prompt_tokens": self.prompt_tokens,
            "prompt_component_tokens": dict(self.prompt_component_tokens),
            "required_state_fields": list(self.required_state_fields),
            "state_slice_applied": self.state_slice_applied,
            "state_trimmed": self.state_trimmed,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "CompiledPromptSnapshot":
        if not isinstance(payload, dict):
            raise ValueError("CompiledPromptSnapshot must be an object")
        schema = payload.get("output_schema", {})
        if isinstance(schema, dict):
            schema_name = str(
                payload.get("output_schema_name", schema.get("name", ""))
            )
            schema_fields = payload.get(
                "output_schema_fields", schema.get("fields", [])
            )
        else:
            schema_name = str(payload.get("output_schema_name", ""))
            schema_fields = payload.get("output_schema_fields", [])
        if not isinstance(schema_fields, list):
            raise ValueError("CompiledPromptSnapshot output schema fields must be a list")
        components = payload.get("prompt_component_tokens", {})
        if not isinstance(components, dict):
            raise ValueError("CompiledPromptSnapshot token components must be an object")
        contract_version = str(
            payload.get(
                "contract_version",
                payload.get("prompt_contract_version", ""),
            )
        )
        prompt_hash = str(payload.get("prompt_sha256", payload.get("prompt_hash", "")))
        return cls(
            role_directory=str(payload.get("role_directory", "")),
            profile=str(payload.get("profile", "")),
            protocol_version=str(payload.get("protocol_version", PROTOCOL_SCHEMA_VERSION)),
            contract_version=contract_version,
            contract_sha256=str(payload.get("contract_sha256", "")),
            prompt_sha256=prompt_hash,
            output_schema_name=schema_name,
            output_schema_fields=tuple(str(item) for item in schema_fields),
            selected_skill_summary=str(payload.get("selected_skill_summary", "")),
            max_output_cap=int(payload.get("max_output_cap", 0)),
            prompt_tokens=int(payload.get("prompt_tokens", 0)),
            prompt_component_tokens={str(k): int(v) for k, v in components.items()},
            required_state_fields=tuple(
                str(item) for item in payload.get("required_state_fields", [])
            ),
            state_slice_applied=bool(payload.get("state_slice_applied", False)),
            state_trimmed=bool(payload.get("state_trimmed", False)),
        )

    @staticmethod
    def assert_contract_binding(
        before: "CompiledPromptSnapshot",
        after: "CompiledPromptSnapshot",
    ) -> None:
        if before.contract_sha256 != after.contract_sha256:
            if before.prompt_sha256 == after.prompt_sha256:
                raise AssertionError(
                    "Prompt contract changed without changing compiled prompt hash"
                )


PromptSnapshot = CompiledPromptSnapshot


@dataclass(frozen=True)
class PromptSpec:
    role_directory: str
    profile: str
    contract: PromptContract
    runtime_protocol: str
    output_schema_fields: tuple[str, ...] = ()
    output_schema_name: str = ""
    compact_contract: bool = True

    def system_prompt(self) -> str:
        if self.compact_contract:
            return self.contract.render_compact_system(self.runtime_protocol)
        return self.contract.render_system(self.runtime_protocol)


class PromptCompiler:
    """Compile concise role/problem-specific prompts from immutable contracts."""

    def __init__(
        self,
        contracts: PromptContractLoader | None = None,
    ) -> None:
        self._contracts = contracts or PromptContractLoader()
        self._token_counter = InternS2TokenCounter()

    @staticmethod
    def required_state_fields(role_directory: str) -> tuple[str, ...]:
        """Expose the immutable state declaration used by a stage."""

        return tuple(REQUIRED_STATE_FIELDS.get(str(role_directory), ()))

    def compile_solver(
        self,
        role_directory: str,
        *,
        problem: ProblemIR,
        route: RoutePlan,
        user_content: str,
        runtime_instructions: str = "",
        autonomous: bool = False,
        compact: bool = False,
        protocol_variant: str = PROTOCOL_SCHEMA_VERSION,
        semantic_payload: bool = False,
    ) -> PromptCompilation:
        if role_directory not in {"primary_solver", "alternative_solver"}:
            raise ValueError("solver prompt role is invalid")
        profile = self.solver_profile(problem, route)
        output_profile = self.candidate_output_profile(problem, route)
        instructions = [
            _candidate_profile_protocol(
                output_profile,
                autonomous=autonomous,
                protocol_variant=protocol_variant,
                semantic_payload=semantic_payload,
            ),
            self._response_mode_protocol(problem),
            self._solver_profile_protocol(profile),
        ]
        if protocol_variant == LITE_PROTOCOL_SCHEMA_VERSION:
            instructions.append(
                "使用 AgentTurnPayload 1.1-lite：完整解答用 action=publish_candidate，"
                "语义 Candidate 放入 payload，outbound=[]、stop_reason=candidate_complete；"
                "无法保证正确时用 abstain 并给出非空 stop_reason。"
            )
        elif autonomous:
            instructions.append(
                "完整解答用 task_result_type=CandidateArtifact、action=publish_candidate，"
                f"将完整 {output_profile} Candidate 放入 result_payload，public_state_delta={{}}、"
                "outbound_intents=[]；无法保证正确时用 abstain/CheckpointArtifact 并说明原因。"
            )
            instructions.append(
                "Canonical ActionRegistry actions for this Candidate Turn: "
                + ", ".join(
                    _ACTION_REGISTRY.prompt_actions(
                        _ROLE_DIRECTORY_TO_ROLE[role_directory],
                        phase="candidate",
                    )
                )
                + "."
            )
        if compact:
            instructions.append(
                "这是 compact_synthesis 恢复回合：只消费已验证公共 Artifact 摘要，"
                "返回最小完整 Candidate，不重复已丢弃的长回复。"
            )
        if role_directory == "alternative_solver":
            instructions.append(
                "避开 forbidden method families 独立求解，不重构或模仿 Primary 解答。"
            )
        if profile == "tool":
            tools = self._prioritized_tools(route.selected_tools)
            if tools:
                instructions.append(
                    "为 Host 的确定性检查明确写出表达式、域、假设或有限情形；授权工具为："
                    + ", ".join(tools[:3])
                    + "。Do not emit tool arguments or calls（不得输出工具参数或调用）。"
                )
        if runtime_instructions.strip():
            instructions.append(runtime_instructions.strip())
        output_tokens = _SOLVER_OUTPUT_TOKENS[profile][role_directory]
        instructions.append(
            f"本 Candidate Turn 输出上限为 {output_tokens:,} tokens；这是单回合上限，不是单题推理预算。"
        )
        return self._compile(
            role_directory,
            profile,
            user_content,
            "\n".join(instructions),
            output_tokens,
            output_schema_fields=(
                tuple(sorted(LITE_AGENT_TURN_FIELDS))
                if protocol_variant == LITE_PROTOCOL_SCHEMA_VERSION
                else tuple(sorted(AGENT_TURN_FIELDS))
                if autonomous
                else (
                    tuple(sorted(MODEL_SEMANTIC_REQUIRED_FIELDS))
                    if semantic_payload
                    else tuple(sorted(MODEL_CANDIDATE_PROFILE_FIELDS[output_profile]))
                )
            ),
            output_schema_name=(
                f"agent_turn:1.1-lite:candidate:{output_profile}"
                if protocol_variant == LITE_PROTOCOL_SCHEMA_VERSION
                else f"agent_turn:candidate:{output_profile}"
                if autonomous
                else f"candidate:semantic:{output_profile}"
                if semantic_payload
                else f"candidate:{output_profile}"
            ),
            protocol_version=protocol_variant,
        )

    def compile_solver_progress(
        self,
        role_directory: str,
        *,
        problem: ProblemIR,
        route: RoutePlan,
        user_content: str,
        mode: str,
        runtime_instructions: str = "",
        autonomous: bool = False,
        protocol_variant: str = PROTOCOL_SCHEMA_VERSION,
    ) -> PromptCompilation:
        if role_directory not in {"primary_solver", "alternative_solver"}:
            raise ValueError("solver progress prompt role is invalid")
        if mode not in {"explore", "continue"}:
            raise ValueError("progress mode must be explore or continue")
        profile = self.solver_profile(problem, route)
        role = (
            "PrimarySolver"
            if role_directory == "primary_solver"
            else "AlternativeSolver"
        )
        instructions = [
            _progress_delta_protocol(
                mode,
                autonomous=autonomous,
                role=role,
                protocol_variant=protocol_variant,
            )
        ]
        if protocol_variant == LITE_PROTOCOL_SCHEMA_VERSION:
            instructions.append(
                "使用 AgentTurnPayload 1.1-lite：将公共 ProgressDelta 放入 payload；Host 提供类型、ID、状态和摘要。"
            )
        elif autonomous:
            instructions.append(
                "使用 task_result_type=ProgressArtifact；ProgressDelta 放入 public_state_delta，result_payload={}。"
                f"允许动作：{', '.join(_ACTION_REGISTRY.prompt_actions(role, phase='progress'))}；"
                "complete 时 stop_reason 非空。继续必须新增 Claim/Subgoal/义务转移/具体请求，禁止只改措辞。"
            )
        if mode == "explore":
            instructions.append(
                "拆解精确目标并建立首批公共 Claims；保留 ProblemFrame 的条件、定义、量词和目标。"
            )
        else:
            instructions.append(
                "只消费提供的公共 ReasoningState；推进少量开放 Subgoal，明确关闭或保留义务，不重复未变状态。"
            )
        if runtime_instructions.strip():
            instructions.append(runtime_instructions.strip())
        return self._compile(
            role_directory,
            f"{profile}:{mode}",
            user_content,
            "\n".join(instructions),
            12288,
            output_schema_fields=(
                tuple(sorted(LITE_AGENT_TURN_FIELDS))
                if protocol_variant == LITE_PROTOCOL_SCHEMA_VERSION
                else tuple(sorted(AGENT_TURN_FIELDS))
                if autonomous
                else _PROGRESS_DELTA_FIELDS
            ),
            output_schema_name=(
                f"agent_turn:1.1-lite:progress:{mode}"
                if protocol_variant == LITE_PROTOCOL_SCHEMA_VERSION
                else f"agent_turn:progress:{mode}"
                if autonomous
                else f"progress:{mode}"
            ),
            protocol_version=protocol_variant,
        )

    def compile_emergency_answer(
        self,
        *,
        problem: ProblemIR,
        user_content: str,
    ) -> PromptCompilation:
        instructions = "\n".join(
            (
                _candidate_profile_protocol("answer_only", autonomous=False),
                self._response_mode_protocol(problem),
                "This is the final gradeability fallback. Solve the problem "
                "directly and return the exact scorer-facing answer plus one "
                "short public check. Do not emit an AgentTurn envelope.",
            )
        )
        return self._compile(
            "primary_solver",
            "emergency_direct",
            user_content,
            instructions,
            2048,
            output_schema_fields=tuple(
                sorted(MODEL_CANDIDATE_PROFILE_FIELDS["answer_only"])
            ),
            output_schema_name="candidate:answer_only",
        )

    def compile_solver_collaboration(
        self,
        role_directory: str,
        *,
        user_content: str,
        mode: str,
    ) -> PromptCompilation:
        if role_directory not in {"primary_solver", "alternative_solver"}:
            raise ValueError("solver collaboration role is invalid")
        if mode == "peer_review":
            protocol = _PEER_REVIEW_PROTOCOL
        elif mode == "respond_to_review":
            protocol = _REBUTTAL_PROTOCOL
        else:
            raise ValueError("solver collaboration mode is invalid")
        role = _ROLE_DIRECTORY_TO_ROLE[role_directory]
        phase = (
            "peer_review_turn"
            if mode == "peer_review"
            else "rebuttal_turn"
        )
        protocol += (
            "\nCanonical ActionRegistry actions for this Turn: "
            + ", ".join(_ACTION_REGISTRY.prompt_actions(role, phase=phase))
            + "."
        )
        return self._compile(
            role_directory,
            mode,
            user_content,
            protocol,
            stage_output_cap("peer_review"),
            output_schema_fields=tuple(sorted(AGENT_TURN_FIELDS)),
            output_schema_name=f"agent_turn:collaboration:{mode}",
        )

    def compile_verifier_closure(
        self,
        *,
        user_content: str,
        mode: str,
    ) -> PromptCompilation:
        if mode == "cross_exam":
            protocol = _CROSS_EXAM_PROTOCOL
        elif mode == "final_audit":
            protocol = _FINAL_AUDIT_PROTOCOL
        else:
            raise ValueError("Verifier closure mode is invalid")
        protocol += (
            "\nCanonical ActionRegistry actions for this Turn: "
            + ", ".join(
                _ACTION_REGISTRY.prompt_actions(
                    "VerifierSkeptic",
                    phase=(
                        "final_audit_turn"
                        if mode == "final_audit"
                        else "verifier_turn"
                    ),
                )
            )
            + "."
        )
        return self._compile(
            "verifier_skeptic",
            mode,
            user_content,
            protocol,
            stage_output_cap("verifier"),
            output_schema_fields=tuple(sorted(AGENT_TURN_FIELDS)),
            output_schema_name=f"agent_turn:verifier:{mode}",
        )

    def compile_role(
        self,
        role_directory: str,
        *,
        user_content: str,
        runtime_instructions: str = "",
    ) -> PromptCompilation:
        protocol = _ROLE_PROTOCOLS.get(role_directory)
        if protocol is None:
            raise ValueError(f"role prompt compiler is unavailable: {role_directory}")
        instructions = protocol
        role = _ROLE_DIRECTORY_TO_ROLE[role_directory]
        instructions += (
            "\nCanonical ActionRegistry actions for this role: "
            + ", ".join(_ACTION_REGISTRY.prompt_actions(role))
            + "."
        )
        if runtime_instructions.strip():
            instructions += "\n" + runtime_instructions.strip()
        stage = _ROLE_DIRECTORY_TO_STAGE[role_directory]
        schema_fields = {
            "router_planner": tuple(sorted(ROUTER_INTENT_FIELDS)),
            "lemma_curator": tuple(sorted(AGENT_TURN_FIELDS)),
            "verifier_skeptic": ("findings",),
            "repair": tuple(sorted(MODEL_CANDIDATE_PATCH_FIELDS)),
            "finalizer": ("final_answer", "solution_text"),
        }[role_directory]
        return self._compile(
            role_directory,
            stage,
            user_content,
            instructions,
            stage_output_cap(stage),
            output_schema_fields=schema_fields,
            output_schema_name=f"role:{role_directory}:{stage}",
        )

    @staticmethod
    def candidate_output_profile(problem: ProblemIR, route: RoutePlan) -> str:
        del route
        return candidate_profile_for_response_mode(problem.response_mode)

    @staticmethod
    def solver_profile(problem: ProblemIR, route: RoutePlan) -> str:
        if problem.problem_type in {"proof", "derivation"}:
            return "proof"
        specialized_tools = {
            "numerical_residual",
            "matrix_shape_check",
            "density_normalization",
            "small_case_enumeration",
        }
        if specialized_tools.intersection(route.selected_tools):
            return "tool"
        if (
            problem.problem_type in {"calculation", "fill_blank", "multiple_choice"}
            and len(problem.normalized_problem) <= 240
            and len(problem.assumptions) <= 2
            and route.risk_level != "high"
        ):
            return "minimal"
        return "standard"

    @staticmethod
    def bounded_output_tokens(configured: int, compiled: int) -> int:
        if type(configured) is not int or configured < 0:
            raise ValueError("configured output tokens must be nonnegative")
        return compiled if configured == 0 else min(configured, compiled)

    @staticmethod
    def _solver_profile_protocol(profile: str) -> str:
        if profile == "minimal":
            return "只做一次直接公共检查并结束紧凑 JSON。"
        if profile == "proof":
            return (
                "给出完整有序证明，写明定理条件、必要性/充分性（适用时）和全部未闭条件。"
            )
        if profile == "tool":
            return (
                "明确表达式、定义域、假设、矩阵、区间或有限情形，便于 Host 安全检查。"
            )
        return "给出含明确条件的简洁公共推导，不重复题目或协议。"

    @staticmethod
    def _response_mode_protocol(problem: ProblemIR) -> str:
        if problem.response_mode == "proof_full":
            return (
                "Host response mode is proof_full. proof_steps must contain the "
                "complete public proof, including essential inferences, theorem hypotheses, boundary cases, and the conclusion。"
            )
        if problem.response_mode == "worked_solution":
            return (
                "Host response mode is worked_solution. steps must be an ordered, "
                "independently checkable complete derivation with semantic claim_kind。"
            )
        return (
            "Host response mode is answer_only. Give the exact canonical answer and "
            "the shortest independently checkable public semantic check。"
        )

    def _compile(
        self,
        role_directory: str,
        profile: str,
        user_content: str,
        instructions: str,
        output_tokens: int,
        *,
        output_schema_fields: tuple[str, ...] = (),
        output_schema_name: str = "",
        protocol_version: str = PROTOCOL_SCHEMA_VERSION,
        selected_skill_summary: str = "",
        component_texts: dict[str, str] | None = None,
    ) -> PromptCompilation:
        if protocol_version not in {PROTOCOL_SCHEMA_VERSION, LITE_PROTOCOL_SCHEMA_VERSION}:
            raise ValueError("unsupported AgentTurnPayload protocol version")
        contract = self._contracts.load(role_directory)
        user_content, state_slice_applied = _declared_state_slice(
            str(user_content),
            role_directory,
        )
        instructions = _CHINESE_LANGUAGE_DIRECTIVE + "\n" + str(instructions).strip()
        spec = PromptSpec(
            role_directory=role_directory,
            profile=profile,
            contract=contract,
            runtime_protocol=instructions,
            output_schema_fields=output_schema_fields,
            output_schema_name=output_schema_name,
        )
        system = spec.system_prompt()
        prompt_chars = len(system) + len(user_content)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
        counted_prompt = self._token_counter.count_messages(messages)
        schema_text = json.dumps(
            {
                "name": output_schema_name,
                "fields": list(output_schema_fields),
                "protocol_version": protocol_version,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        component_sources = self._prompt_component_sources(
            contract=contract,
            instructions=instructions,
            user_content=user_content,
            schema_text=schema_text,
            selected_skill_summary=selected_skill_summary,
            explicit=component_texts,
        )
        component_counts = {
            name: self._token_counter.count_text(text).tokens
            for name, text in component_sources.items()
        }
        # The problem is the highest-value context.  If state/skills/schema
        # crowd it out, trim only the marked state section until the dynamic
        # prompt share is at least 45%.  Fixed contract and protocol text is
        # reported separately and is not silently deleted.
        state_trimmed = False
        dynamic_total = sum(
            component_counts[name]
            for name in ("problem_tokens", "state_tokens", "skill_tokens")
        )
        problem_share = (
            component_counts["problem_tokens"] / dynamic_total
            if dynamic_total
            else 1.0
        )
        if problem_share < 0.45 and component_counts["state_tokens"] > 0:
            non_state = sum(
                component_counts[name]
                for name in ("problem_tokens", "skill_tokens")
            )
            state_allowance = max(
                0,
                floor(component_counts["problem_tokens"] / 0.45 - non_state),
            )
            trimmed_user = _trim_marked_state(
                user_content,
                state_allowance,
                self._token_counter,
            )
            if trimmed_user != user_content:
                user_content = trimmed_user
                state_trimmed = True
                prompt_chars = len(system) + len(user_content)
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ]
                counted_prompt = self._token_counter.count_messages(messages)
                component_sources = self._prompt_component_sources(
                    contract=contract,
                    instructions=instructions,
                    user_content=user_content,
                    schema_text=schema_text,
                    selected_skill_summary=selected_skill_summary,
                    explicit=component_texts,
                )
                component_counts = {
                    name: self._token_counter.count_text(text).tokens
                    for name, text in component_sources.items()
                }
        if prompt_chars > contract.max_context_chars:
            raise ContextBudgetExceeded(
                f"{contract.fields['role']} messages require {prompt_chars} chars, "
                f"budget is {contract.max_context_chars}"
            )
        dynamic_total = sum(
            component_counts[name]
            for name in ("problem_tokens", "state_tokens", "skill_tokens")
        )
        problem_share = (
            component_counts["problem_tokens"] / dynamic_total
            if dynamic_total
            else 1.0
        )
        if component_counts["state_tokens"] and problem_share < 0.45:
            # This is intentionally an assertion rather than a warning: a
            # state-bearing prompt that still fails the share gate is unsafe
            # to dispatch.  A short problem with no state remains valid.
            raise AssertionError(
                "problem_tokens/total dynamic prompt tokens must be >= 0.45 "
                "after state trimming"
            )
        skill_summary = selected_skill_summary.strip() or self._skill_summary(user_content)
        prompt_digest = sha256(
            json.dumps(
                messages,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return PromptCompilation(
            profile=profile,
            messages=messages,
            max_output_tokens=output_tokens,
            prompt_chars=prompt_chars,
            output_schema_fields=output_schema_fields,
            output_schema_name=output_schema_name,
            prompt_sha256=prompt_digest,
            contract_sha256=contract.source_sha256,
            role_directory=role_directory,
            protocol_version=protocol_version,
            contract_version=contract.fields.get("version", ""),
            selected_skill_summary=skill_summary,
            prompt_tokens=counted_prompt.tokens,
            prompt_counting_mode=counted_prompt.counting_mode,
            tokenizer_revision=counted_prompt.tokenizer_revision,
            tokenizer_sha256=counted_prompt.tokenizer_sha256,
            contract_tokens=component_counts["contract_tokens"],
            runtime_protocol_tokens=component_counts["runtime_protocol_tokens"],
            skill_tokens=component_counts["skill_tokens"],
            state_tokens=component_counts["state_tokens"],
            problem_tokens=component_counts["problem_tokens"],
            schema_tokens=component_counts["schema_tokens"],
            prompt_component_tokens=component_counts,
            required_state_fields=tuple(
                REQUIRED_STATE_FIELDS.get(role_directory, ())
            ),
            state_slice_applied=state_slice_applied,
            state_trimmed=state_trimmed,
        )

    @staticmethod
    def _skill_summary(user_content: str) -> str:
        names = [
            line.strip()[len("# Skill:") :].strip()
            for line in user_content.splitlines()
            if line.strip().startswith("# Skill:")
        ]
        return ", ".join(dict.fromkeys(name for name in names if name))

    @staticmethod
    def _prompt_component_sources(
        *,
        contract: PromptContract,
        instructions: str,
        user_content: str,
        schema_text: str,
        selected_skill_summary: str,
        explicit: dict[str, str] | None,
    ) -> dict[str, str]:
        if explicit is not None:
            missing = {
                "contract_tokens",
                "runtime_protocol_tokens",
                "skill_tokens",
                "state_tokens",
                "problem_tokens",
                "schema_tokens",
            } - set(explicit)
            if missing:
                raise ValueError(
                    "prompt component telemetry is missing: "
                    + ", ".join(sorted(missing))
                )
            return {name: str(explicit[name]) for name in sorted(explicit)}
        skill_text = selected_skill_summary.strip()
        if not skill_text:
            skill_text = "\n".join(
                line for line in user_content.splitlines() if "# Skill:" in line
            )
        state_text = _state_sections(user_content)
        problem_text = _problem_section(user_content)
        # Generic role payloads do not always carry a Problem: prefix.  They
        # are still useful prompt content; count them as the problem-bearing
        # portion rather than dropping telemetry to zero.
        if not problem_text:
            problem_text = user_content
        return {
            "contract_tokens": contract.render_compact_system(""),
            "runtime_protocol_tokens": instructions,
            "skill_tokens": skill_text,
            "state_tokens": state_text,
            "problem_tokens": problem_text,
            "schema_tokens": schema_text,
        }

    @staticmethod
    def _prioritized_tools(tools: list[str]) -> list[str]:
        specialized = {
            "numerical_residual",
            "matrix_shape_check",
            "density_normalization",
            "small_case_enumeration",
        }
        generic = {"answer_type_check", "latex_syntax_check"}
        return [
            *[name for name in tools if name in specialized],
            *[
                name
                for name in tools
                if name not in specialized and name not in generic
            ],
            *[name for name in tools if name in generic],
        ]
