from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError, field_validator

sys.path.insert(0, "src")
from model_client import ModelClient


class PlannerOutput(BaseModel):
    tags: list[str]
    summary: str

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        if len(value) != 3:
            raise ValueError("There must be exactly three tags.")

        for tag in value:
            if not isinstance(tag, str):
                raise ValueError("Every tag must be a string.")

            if not 3 <= len(tag.strip()) <= 30:
                raise ValueError(
                    "Every tag must contain between 3 and 30 characters."
                )

        return [tag.strip() for tag in value]

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        word_count = len(re.findall(r"\b[\w'-]+\b", value))

        if word_count > 25:
            raise ValueError("The summary must contain at most 25 words.")

        return value.strip()


class ReviewOutput(BaseModel):
    approved: bool
    feedback: str


class AgentState(TypedDict, total=False):
    title: str
    content: str
    llm: Any
    turn_ceiling: int
    turn_count: int
    planner_attempts: int
    planner_proposal: dict[str, Any]
    reviewer_feedback: dict[str, Any]
    validation_error: str
    status: str


PLANNER_SYSTEM = """You are Planner.

Given a title and body, return valid JSON with:
- exactly three topical tags
- each tag must be 3 to 30 characters
- a summary of at most 25 words

Do not copy the title or body into the tags.
Return only JSON with keys: tags and summary."""


REVIEWER_SYSTEM = """You are Reviewer.

Review the Planner JSON against the original title and body.
Approve it only if the tags are relevant and the summary is factual and concise.
Return only JSON with:
- approved: true or false
- feedback: a short explanation

Do not rewrite the proposal."""


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)

        if not match:
            raise ValueError("The model did not return a JSON object.")

        return json.loads(match.group(0))


def planner_node(state: AgentState) -> dict[str, Any]:
    print("--- NODE: Planner ---")

    planner_attempts = state.get("planner_attempts", 0) + 1

    previous_error = state.get("validation_error", "")
    previous_feedback = state.get("reviewer_feedback", {})

    correction = ""

    if previous_error:
        correction += (
            "\nPrevious validation error. Fix it carefully:\n"
            + previous_error
        )

    if previous_feedback:
        correction += (
            "\nReviewer feedback from the previous attempt:\n"
            + json.dumps(previous_feedback)
        )

    source = (
        f"Title: {state['title']}\n\n"
        f"Body:\n{state['content']}\n"
        f"{correction}"
    )

    result = state["llm"].complete(
        [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": source},
        ],
        temperature=0.2,
        format=PlannerOutput.model_json_schema(),
    )

    try:
        proposal = PlannerOutput.model_validate(extract_json(result.text))

        return {
            "planner_proposal": proposal.model_dump(),
            "validation_error": "",
            "planner_attempts": planner_attempts,
        }

    except (ValidationError, ValueError, TypeError) as exc:
        print(f"Planner validation failed: {exc}")

        return {
            "planner_proposal": {},
            "validation_error": str(exc),
            "planner_attempts": planner_attempts,
        }


def reviewer_node(state: AgentState) -> dict[str, Any]:
    print("--- NODE: Reviewer ---")

    source = (
        f"Title: {state['title']}\n\n"
        f"Body:\n{state['content']}\n\n"
        f"Planner proposal:\n"
        f"{json.dumps(state['planner_proposal'])}"
    )

    result = state["llm"].complete(
        [
            {"role": "system", "content": REVIEWER_SYSTEM},
            {"role": "user", "content": source},
        ],
        temperature=0.0,
        format=ReviewOutput.model_json_schema(),
    )

    try:
        review = ReviewOutput.model_validate(extract_json(result.text))
        feedback = review.model_dump()

    except (ValidationError, ValueError, TypeError) as exc:
        feedback = {
            "approved": False,
            "feedback": f"Reviewer output was invalid: {exc}",
        }

    return {"reviewer_feedback": feedback}


def supervisor_node(state: AgentState) -> dict[str, Any]:
    print("--- NODE: Supervisor ---")

    next_turn = state.get("turn_count", 0) + 1
    ceiling = state.get("turn_ceiling", 10)
    feedback = state.get("reviewer_feedback", {})

    status = "running"

    if feedback.get("approved") is True:
        status = "completed"
    elif next_turn > ceiling:
        status = "abandoned"

    return {
        "turn_count": next_turn,
        "status": status,
    }


def router_logic(state: AgentState) -> str:
    ceiling = state.get("turn_ceiling", 10)

    if state.get("status") in {"completed", "abandoned"}:
        return "end"

    if state.get("validation_error"):
        if state.get("turn_count", 0) <= ceiling:
            return "planner"

        return "end"

    feedback = state.get("reviewer_feedback", {})

    if feedback.get("approved") is True:
        return "end"

    if feedback and state.get("turn_count", 0) < ceiling:
        return "planner"

    if not state.get("planner_proposal"):
        return "planner"

    return "reviewer"


def after_planner_route(state: AgentState) -> str:
    if state.get("validation_error"):
        return "supervisor"

    return "reviewer"


def build_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("reviewer", reviewer_node)

    workflow.add_edge(START, "supervisor")

    workflow.add_conditional_edges(
        "supervisor",
        router_logic,
        {
            "planner": "planner",
            "reviewer": "reviewer",
            "end": END,
        },
    )

    workflow.add_conditional_edges(
        "planner",
        after_planner_route,
        {
            "supervisor": "supervisor",
            "reviewer": "reviewer",
        },
    )

    workflow.add_edge("reviewer", "supervisor")

    return workflow.compile()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--content", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--turn-ceiling", type=int, default=10)
    args = parser.parse_args()

    client = ModelClient(model=args.model) if args.model else ModelClient()

    initial_state: AgentState = {
        "title": args.title,
        "content": args.content,
        "llm": client,
        "turn_ceiling": args.turn_ceiling,
        "turn_count": 0,
        "planner_attempts": 0,
        "planner_proposal": {},
        "reviewer_feedback": {},
        "validation_error": "",
        "status": "running",
    }

    graph = build_graph()
    final_state = dict(initial_state)

    for update in graph.stream(initial_state):
        print(json.dumps(update, indent=2, default=str))

        for node_update in update.values():
            final_state.update(node_update)

    print("\nGraph execution finished.")
    print(json.dumps(final_state, indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())