from threading import BoundedSemaphore
from uuid import uuid4

from mathforge.config import HarnessConfig, load_competition_config
from mathforge.model_identity import official_client_model_identity
from mathforge.harness.terminalizer import MINIMAL_FALLBACK_RESPONSE
from mathforge.output.public_result import (
    build_public_result,
    identifier_from_metadata,
)
from mathforge.output.official_trace import minimal_official_trace
from mathforge.output.deterministic_formatter import exact_final_answer
from mathforge.parsing.answer_salvage import salvage_any_answer
from mathforge.runtime import MathForgeHarness


CASE_MAX_CONCURRENCY = load_competition_config().case_max_concurrency


class ReasoningAgent:
    def __init__(self, client, *args, **kwargs):
        config = kwargs.pop("config", None)
        del args, kwargs
        if config is not None and not isinstance(config, HarnessConfig):
            raise TypeError("config must be a HarnessConfig")
        active_config = config or load_competition_config()
        self._harness = MathForgeHarness(
            client,
            active_config,
            model_identity=official_client_model_identity(),
        )
        self._case_gate = BoundedSemaphore(active_config.case_max_concurrency)

    def solve(self, problem: str, metadata: dict) -> dict:
        identifier = None
        response_key = uuid4().hex
        result = None
        try:
            with self._case_gate:
                identifier = identifier_from_metadata(metadata)
                result = self._harness.solve(
                    problem,
                    metadata,
                    raw_response_key=response_key,
                )
                return build_public_result(identifier, result)
        except Exception:
            try:
                salvaged = salvage_any_answer(
                    [
                        *(
                            [result.get("final_response", "")]
                            if isinstance(result, dict)
                            else []
                        ),
                        *self._harness.last_raw_responses(response_key),
                    ]
                )
            except Exception:
                salvaged = None
            return {
                "id": identifier,
                "status": "failed",
                "final_response": exact_final_answer(
                    salvaged or MINIMAL_FALLBACK_RESPONSE,
                    "expression",
                ),
                "trace": minimal_official_trace(),
            }
        finally:
            try:
                self._harness.release_raw_responses(response_key)
            except Exception:
                pass
