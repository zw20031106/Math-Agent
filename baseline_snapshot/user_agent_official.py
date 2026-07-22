import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

from lagent.agents import Agent
from lagent.schema import AgentMessage

from llm_client import InternChatClient


# ==================== PARTICIPANT DESIGN AREA START ====================

POLICY_PROMPT = """你是一个严谨的数学推理智能体。
请解决用户给出的数学问题，并给出清晰推理与最终答案。

要求：
1. 先分析题意和关键条件。
2. 给出必要的推导步骤。
3. 在最后明确写出最终答案。
"""

VERIFIER_PROMPT = """你是一个数学答案验证器。
请判断候选解答是否正确解决了题目。

不要输出解释。只输出以下两行之一：
VERDICT: A
或
VERDICT: B

其中 A 表示候选解答正确，B 表示候选解答错误。
"""


@dataclass
class AgentConfig:
    policy_sample_times: int = 3
    verifier_voting_times: int = 2
    policy_temperature: float = 0.6
    verifier_temperature: float = 0.0
    max_tokens: int = 4096


class ReasoningAgent:
    """A simple lagent-based generate-verify-select baseline agent."""

    def __init__(self, client: InternChatClient, config: AgentConfig | None = None) -> None:
        self.config = config or AgentConfig()
        self.policy_agent = Agent(
            llm=client,
            template=POLICY_PROMPT,
            name="policy_agent",
        )
        self.verifier_agent = Agent(
            llm=client,
            template=VERIFIER_PROMPT,
            name="verifier_agent",
        )

    def solve(self, problem: str, metadata: Dict) -> Dict:
        idx = metadata.get("idx", 0)
        candidates, trace = self._generate_candidates(problem, idx)
        scored_candidates = []

        for candidate_id, candidate in enumerate(candidates):
            confidence, verify_trace = self._verify_candidate(
                problem,
                candidate,
                idx,
                candidate_id,
            )
            scored_candidates.append(
                {
                    "content": candidate,
                    "confidence_score": confidence,
                }
            )
            trace.extend(verify_trace)

        best = max(scored_candidates, key=lambda item: item["confidence_score"])
        trace.append(
            {
                "step": "select_final_response",
                "content": f"Selected candidate with confidence {best['confidence_score']:.3f}.",
            }
        )
        return {
            "final_response": best["content"],
            "trace": trace,
        }

    def _generate_candidates(self, problem: str, idx: int) -> Tuple[List[str], List[Dict]]:
        candidates = []
        trace = []
        for sample_id in range(self.config.policy_sample_times):
            user_message = AgentMessage(
                sender="user",
                content=f"题目：\n{problem}\n\n请给出完整解答。候选编号：{sample_id}",
            )
            response = self.policy_agent(
                user_message,
                session_id=f"{idx}:policy:{sample_id}",
                temperature=self.config.policy_temperature,
                max_tokens=self.config.max_tokens,
            )
            candidates.append(response.content)
            trace.append(
                {
                    "step": f"policy_call_{sample_id}",
                    "content": {
                        "message": user_message.content,
                        "response": response.content,
                    },
                }
            )
        return candidates, trace

    def _verify_candidate(
        self,
        problem: str,
        candidate: str,
        idx: int,
        candidate_id: int,
    ) -> Tuple[float, List[Dict]]:
        votes = []
        trace = []
        for vote_id in range(self.config.verifier_voting_times):
            user_message = AgentMessage(
                sender="user",
                content=(
                    "题目：\n"
                    f"{problem}\n\n"
                    "候选解答：\n"
                    f"{candidate}\n\n"
                    "请判断候选解答是否正确。\n"
                    "只输出一行：VERDICT: A 或 VERDICT: B。"
                ),
            )
            response = self.verifier_agent(
                user_message,
                session_id=f"{idx}:verify:{candidate_id}:{vote_id}",
                temperature=self.config.verifier_temperature,
                max_tokens=1024,
            )
            verdict = response.content
            votes.append(self._is_correct_vote(verdict))
            trace.append(
                {
                    "step": f"verifier_call_{candidate_id}_{vote_id}",
                    "content": {
                        "candidate_id": candidate_id,
                        "message": user_message.content,
                        "response": verdict,
                    },
                }
            )

        confidence = sum(votes) / len(votes) if votes else 0.0
        return confidence, trace

    @staticmethod
    def _is_correct_vote(verdict: str) -> bool:
        verdict_matches = re.findall(
            r"\bVERDICT\s*[:：]\s*([AB])\s*[。.]?",
            verdict,
            flags=re.IGNORECASE,
        )
        if verdict_matches:
            return verdict_matches[-1].upper() == "A"

        label_matches = re.findall(
            r"^\s*([AB])\s*[。.]?\s*$",
            verdict,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if label_matches:
            return label_matches[-1].upper() == "A"

        words = re.findall(r"\b[A-Z]+\b", verdict.upper())
        if "INCORRECT" in words:
            return False
        return "CORRECT" in words


# ===================== PARTICIPANT DESIGN AREA END =====================
