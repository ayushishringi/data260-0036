"""HW10 Parts 2-3: DeepEval GEval metrics scored by the local Ollama model (1-5 scale).

Judge model: Ollama qwen3:4b (the same local model the agents use; no paid API), temperature 0,
seed 36, num_ctx 16384, thinking on (HW10_JUDGE_THINK=1; the reasoning is returned separately and
is not parsed), and Ollama structured output (format = the JSON schema DeepEval asks for).
Thinking off is ~25x faster but scored a reasonable 3-step plan 1/5 in a spot check, so it stays on.

Scale: each GEval metric has a 5-band rubric with score ranges (1,1)...(5,5), so the judge answers
1-5 directly. DeepEval normalizes that to 0-1; score_1_5() maps it back (1 + 4 * score).
evaluation_steps are fixed below, so DeepEval does not generate (and vary) its own steps per run.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
os.environ.setdefault("DEEPEVAL_DISABLE_DOTENV", "1")

from deepeval.metrics import GEval  # noqa: E402
from deepeval.metrics.g_eval import Rubric  # noqa: E402
from deepeval.models import DeepEvalBaseLLM  # noqa: E402
from deepeval.test_case import LLMTestCase, SingleTurnParams  # noqa: E402

from src.model_client import DEFAULT_HOST, DEFAULT_MODEL, DEFAULT_NUM_CTX, ModelClient  # noqa: E402

JUDGE_THINK = os.getenv("HW10_JUDGE_THINK", "1") == "1"
JUDGE_SETTINGS = {"provider": "ollama", "model": DEFAULT_MODEL, "host": DEFAULT_HOST, "temperature": 0.0,
                  "seed": 36, "num_ctx": DEFAULT_NUM_CTX, "think": JUDGE_THINK, "structured_output": True,
                  "framework": "deepeval GEval", "scale": "1-5 (rubric bands (1,1)..(5,5))"}
JUDGE_TIMEOUT_S = float(os.getenv("HW10_JUDGE_TIMEOUT", "240"))


class OllamaJudge(DeepEvalBaseLLM):
    """DeepEval model backed by the repo's Ollama client; returns the pydantic schema DeepEval asks for."""

    def __init__(self, model: str = DEFAULT_MODEL, temperature: float = 0.0, seed: int = 36) -> None:
        self.temperature, self.seed = temperature, seed
        self.client = ModelClient(model=model)
        super().__init__(model)

    def load_model(self) -> ModelClient:
        return self.client

    def generate(self, prompt: str, schema: Any = None) -> Any:
        fmt = schema.model_json_schema() if schema is not None else None
        result = self.client.complete([{"role": "user", "content": prompt}], temperature=self.temperature,
                                      format=fmt, seed=self.seed, think=JUDGE_THINK)
        return schema.model_validate_json(result.text) if schema is not None else result.text

    async def a_generate(self, prompt: str, schema: Any = None) -> Any:
        return self.generate(prompt, schema)

    def get_model_name(self) -> str:
        return f"ollama/{self.client.model}"


def rubric(outcomes: list[str]) -> list[Rubric]:
    return [Rubric(score_range=(n, n), expected_outcome=text) for n, text in enumerate(outcomes, 1)]


IN, OUT, CTX = SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.RETRIEVAL_CONTEXT
NO_RECORD = ("No s0036_rel advisory record matches this question; judge accuracy from well-established public "
             "knowledge and penalize invented versions, CVEs or severities.")

METRIC_SPECS: dict[str, dict[str, Any]] = {
    "plan_quality": {
        "name": "Plan Quality",
        "params": [IN, OUT],
        "steps": [
            "Read the user question about open-source package vulnerabilities (input) and the Planner's numbered "
            "steps (actual output).",
            "Check whether the steps cover what the question actually asks (for example severity, affected or "
            "fixed version, CVE, impact, or mitigation).",
            "Check whether the steps are specific and actionable for a writer, in a sensible order, without "
            "irrelevant or redundant steps.",
            "Give 5 for a complete, specific, well-ordered plan; 1 for a plan that misses the question.",
        ],
        "rubric": ["Plan ignores or misreads the question.",
                   "Plan touches the topic but misses the main thing asked.",
                   "Plan covers the question partly; steps are vague or include irrelevant work.",
                   "Plan covers the question with minor gaps or one weak step.",
                   "Plan covers exactly what is asked with specific, ordered, actionable steps."],
    },
    "writer_helpfulness": {
        "name": "Writer Helpfulness",
        "params": [IN, OUT, CTX],
        "steps": [
            "Read the question (input) and the Writer's draft (actual output). Retrieval context, when present, "
            "holds the advisory database facts the draft must agree with.",
            "Check accuracy: package, affected versions, fixed version, severity and CVE must match the "
            "retrieval context when it is given, and must not be invented or contradictory.",
            "Check usefulness: the draft answers the question directly and gives concrete, correct guidance "
            "(such as which version to upgrade to).",
            "Lower the score for factual errors, hedging that avoids the answer, or padding that hides it.",
        ],
        "rubric": ["Wrong, off-topic or harmful; does not answer the question.",
                   "Answers partly but contains a major factual error or misses the main point.",
                   "Answers the question with minor errors or significant omissions or padding.",
                   "Accurate and useful with small issues (verbosity, one missing detail).",
                   "Accurate, direct and complete; a practitioner could act on it immediately."],
    },
    "final_helpfulness": {
        "name": "Final Answer Helpfulness",
        "params": [IN, OUT],
        "steps": [
            "Read the user question (input) and the final answer returned to the user (actual output).",
            "Check relevance: the answer addresses the question that was asked, not a different one.",
            "Check helpfulness: the answer is correct as far as can be judged, specific, and actionable.",
            "Lower the score for irrelevant content, contradictions, or an answer the user could not act on.",
        ],
        "rubric": ["Irrelevant or unhelpful.",
                   "Relevant but mostly unhelpful or contains a major error.",
                   "Partly helpful; important gaps or errors.",
                   "Helpful and relevant with small issues.",
                   "Fully helpful, relevant and actionable."],
    },
}


def make_metric(key: str, judge: OllamaJudge) -> GEval:
    spec = METRIC_SPECS[key]
    return GEval(name=spec["name"], evaluation_params=spec["params"], evaluation_steps=spec["steps"],
                 rubric=rubric(spec["rubric"]), model=judge, threshold=0.5, async_mode=False)


def score_1_5(normalized: float) -> float:
    """DeepEval's 0-1 score back on the rubric's 1-5 scale."""

    return round(1 + 4 * float(normalized), 2)


_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="judge")


def judge_ollama_available(timeout: float = 3.0) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"{DEFAULT_HOST}/api/version", timeout=timeout):
            return True
    except OSError:
        return False


def evaluate(key: str, question: str, output: str, context: list[str] | None = None,
             judge: OllamaJudge | None = None, timeout: float | None = None) -> dict[str, Any]:
    """Score one output with one metric. Never raises and never waits longer than `timeout` seconds.

    Returns {"score": 1-5 or None, "reason", "status": ok|error, "error", "judge_ms"}.
    """

    timeout = JUDGE_TIMEOUT_S if timeout is None else timeout
    start = time.time()
    if not isinstance(output, str) or not output.strip():
        return {"score": None, "reason": None, "status": "error", "error": "nothing to judge (empty output)",
                "judge_ms": 0.0}
    metric = make_metric(key, judge or OllamaJudge())
    if CTX in METRIC_SPECS[key]["params"] and not context:
        context = [NO_RECORD]  # GEval rejects an empty retrieval_context; say explicitly there is no record
    case = LLMTestCase(input=question, actual_output=output, retrieval_context=context or None)
    future = _POOL.submit(metric.measure, case, _show_indicator=False)
    try:
        normalized = future.result(timeout=timeout)
        return {"score": score_1_5(normalized), "reason": metric.reason, "status": "ok", "error": None,
                "judge_ms": round((time.time() - start) * 1000, 1)}
    except FutureTimeout:
        error = f"judge timed out after {timeout:.0f}s"
    except Exception as exc:  # unavailable judge, unparseable reply, ...
        error = f"{type(exc).__name__}: {exc}"
    return {"score": None, "reason": None, "status": "error", "error": error[:500],
            "judge_ms": round((time.time() - start) * 1000, 1)}
