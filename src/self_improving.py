"""HW9 Part 4: self-improving two-agent system (Answering Agent + Evaluator Agent).

Answering Agent  - local qwen3:4b. Answers from its own knowledge unless a loaded lesson tells it to
                   look the package up in the s0036_rel advisory table first. On a revision it also
                   receives its previous answer and the evaluator's feedback.
Evaluator Agent  - checks the answer against data/hw9/reference_facts.json (ground truth): the fields
                   the question asks for (fixed version, severity, CVE, affected range) must match the
                   reference; a question about a package with no reference record must be declined
                   without invented versions or CVE IDs. Returns PASS/REVISE, explanation, feedback.
Lessons          - lessons.json entries {lesson_id, failure_pattern, correction, created_at, use_count}
                   plus applies_to (question fields) and action. A lesson is created when the same
                   failure pattern is seen in 2 initial answers (configurable).
At most two answer attempts per question; the loop stops after the second attempt.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "hw9"
REFERENCE = DATA / "reference_facts.json"
MAX_ATTEMPTS = 2
REPEAT_THRESHOLD = 2

FIELD_PATTERNS = {
    "cve": r"\bcve\b(?!-)|\bidentifier\b",
    "severity": r"\bsever|\bhow bad\b",
    "affected_versions": r"\baffected\b|\bvulnerable versions\b",
    "fixed_version": r"\bfix|\bpatch|\bupgrade|\bstops?\b",
}
FIELD_NAMES = {"fixed_version": "first fixed version", "severity": "severity", "cve": "CVE identifier",
               "affected_versions": "affected version range"}
SEVERITIES = ("critical", "high", "medium", "low")
VERSION_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)+(?:-[a-z]+\d*)?(?!\w)", re.I)
CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}", re.I)
DECLINE_RE = re.compile(r"no (?:known |published |public )?(?:advisory|record|information|data|details|cve)"
                        r"|not (?:aware|find|found|able|listed|in the)|cannot (?:find|confirm|verify)|could not find"
                        r"|unable to|(?:don't|do not) have|no such|unknown package|not a known", re.I)


# ----------------------------------------------------------------------------- shared helpers


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def asked_fields(question: str) -> list[str]:
    """Which reference fields a question asks for."""

    fields = [f for f, pattern in FIELD_PATTERNS.items() if re.search(pattern, question, re.I)]
    if "affected_versions" in fields and "fixed_version" in fields:
        fields.remove("fixed_version")  # "affected by ... fix" style questions ask for the range
    return fields or ["fixed_version"]


def has_version(text: str, version: str) -> bool:
    """True if the exact version string appears as its own token."""

    return re.search(rf"(?<![\w.]){re.escape(version)}(?![\w]|\.\d)", text, re.I) is not None


def range_versions(affected: str) -> list[str]:
    return re.findall(r"[<>]=?\s*([\w.\-]+)", affected)


def ask_model(system: str, user: str) -> str:
    from src.model_client import ModelClient
    result = ModelClient().complete([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                    temperature=0.2, think=True)
    return result.text.strip()


class Reference:
    """Ground-truth facts keyed by package name."""

    def __init__(self, path: Path = REFERENCE) -> None:
        self.facts = {f["package"]: f for f in load_json(path)["facts"]}

    def package_in(self, question: str) -> dict[str, Any] | None:
        from src.advisory_lookup import mentions
        for name in sorted(self.facts, key=len, reverse=True):
            if mentions(question, name):
                return self.facts[name]
        return None


# ----------------------------------------------------------------------------- lessons


class LessonStore:
    """lessons.json: reusable lessons with use counts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lessons: list[dict[str, Any]] = load_json(path) if path.exists() else []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.lessons, indent=2) + "\n")

    def relevant(self, question: str) -> list[dict[str, Any]]:
        """Lessons whose applies_to matches a field the question asks for (or 'any')."""

        fields = set(asked_fields(question))
        return [lesson for lesson in self.lessons
                if "any" in lesson["applies_to"] or fields & set(lesson["applies_to"])]

    def mark_used(self, lessons: list[dict[str, Any]]) -> None:
        for lesson in lessons:
            lesson["use_count"] += 1
        if lessons:
            self.save()

    def has_pattern(self, pattern_key: str) -> bool:
        return any(lesson.get("pattern_key") == pattern_key for lesson in self.lessons)

    def add(self, lesson: dict[str, Any]) -> dict[str, Any]:
        lesson = {"lesson_id": f"lesson_{len(self.lessons) + 1:03d}", **lesson}
        self.lessons.append(lesson)
        self.save()
        return lesson


def lesson_for(pattern_key: str, statuses: Counter) -> dict[str, Any]:
    """The reusable lesson written by the Evaluator for a repeated failure pattern."""

    created = date.today().isoformat()
    if pattern_key == "unknown_package":
        return {"failure_pattern": "The answer invents a version, CVE or severity for a package that has no "
                                   "advisory record.",
                "correction": "Look the package up in the s0036_rel advisory database first. If there is no record "
                              "for it, say that no advisory record was found and do not guess versions, CVE IDs or "
                              "severities.",
                "created_at": created, "use_count": 0, "pattern_key": pattern_key, "applies_to": ["any"],
                "action": "lookup_advisory_db"}
    name = FIELD_NAMES[pattern_key]
    wrong = statuses["wrong"] >= statuses["missing"]
    return {"failure_pattern": f"The answer {'gives an incorrect' if wrong else 'omits the'} {name}"
                               f"{' from memory' if wrong else ''}.",
            "correction": f"Before answering a question about the {name}, look the package up in the s0036_rel "
                          f"advisory database and state the {name} exactly as the record gives it.",
            "created_at": created, "use_count": 0, "pattern_key": pattern_key, "applies_to": [pattern_key],
            "action": "lookup_advisory_db"}


# ----------------------------------------------------------------------------- the two agents


class AnsweringAgent:
    """Generates (and revises) answers with the local model."""

    SYSTEM = ("You answer questions about open-source package vulnerabilities in 2-4 sentences of plain text. "
              "Answer exactly what is asked.")

    def answer(self, question: str, lessons: list[dict[str, Any]] | None = None, feedback: str | None = None,
               previous: str | None = None, fault: str | None = None) -> dict[str, Any]:
        """One answer attempt; `fault='incomplete'` returns a deliberately incomplete answer (controlled test)."""

        lessons = lessons or []
        start = time.perf_counter()
        if fault == "incomplete" and feedback is None:
            package = Reference().package_in(question)
            text = (f"There is a known security issue in {package['package'] if package else 'this package'}; "
                    "you should upgrade to a newer release.")
            return {"answer": text, "lessons_used": [], "looked_up": False, "lookup": None, "fault": fault,
                    "latency_ms": round((time.perf_counter() - start) * 1000, 2)}
        system = self.SYSTEM
        if lessons:
            system += "\nLessons from earlier mistakes (follow them):\n" + "\n".join(
                f"- {lesson['correction']}" for lesson in lessons)
        user = f"Question: {question}"
        lookup = None
        if any(lesson.get("action") == "lookup_advisory_db" for lesson in lessons):
            from src.advisory_lookup import fact_line, find_records
            records = find_records(question)
            lookup = [fact_line(r) for r in records]
            user += ("\nAdvisory database (s0036_rel) lookup:\n" + "\n".join(f"- {line}" for line in lookup)
                     if lookup else "\nAdvisory database (s0036_rel) lookup: no record found for the package "
                                    "in this question.")
        if feedback is not None:
            user += f"\nYour previous answer: {previous}\nEvaluator feedback: {feedback}\nWrite a corrected answer."
        text = ask_model(system, user)
        return {"answer": text, "lessons_used": [lesson["lesson_id"] for lesson in lessons],
                "looked_up": lookup is not None, "lookup": lookup, "fault": None,
                "latency_ms": round((time.perf_counter() - start) * 1000, 2)}


class EvaluatorAgent:
    """Checks an answer against the reference dataset."""

    def __init__(self, reference: Reference | None = None) -> None:
        self.reference = reference or Reference()

    def evaluate(self, question: str, answer: str) -> dict[str, Any]:
        """PASS or REVISE with a concise explanation, correction feedback and failure codes."""

        start = time.perf_counter()
        fact = self.reference.package_in(question)
        problems: list[str] = []
        fixes: list[str] = []
        failures: list[dict[str, str]] = []
        fields = asked_fields(question)
        if fact is None:
            invented = sorted(set(CVE_RE.findall(answer)) | set(VERSION_RE.findall(answer)))
            if invented:
                problems.append(f"the package has no reference record but the answer states {', '.join(invented)}")
                failures.append({"pattern": "unknown_package", "status": "unsupported"})
            elif not DECLINE_RE.search(answer):
                problems.append("the package has no reference record and the answer does not say so")
                failures.append({"pattern": "unknown_package", "status": "missing"})
            if failures:
                fixes.append("There is no advisory record for this package in the reference data. Say that no "
                             "advisory record was found and do not state versions, CVE IDs or severities.")
        else:
            for field in fields:
                status, said, expected = self._check(field, fact, answer)
                if status == "ok":
                    continue
                failures.append({"pattern": field, "status": status})
                problems.append(f"{FIELD_NAMES[field]} {'is wrong (' + said + ')' if status == 'wrong' else 'is missing'}")
                fixes.append(f"The reference record for {fact['package']} gives the {FIELD_NAMES[field]} as "
                             f"{expected}; state it exactly.")
        result = "REVISE" if failures else "PASS"
        if result == "PASS":
            explanation = ("Declined correctly: no reference record for this package." if fact is None else
                           f"Matches the reference for {fact['package']} on: "
                           + ", ".join(FIELD_NAMES[f] for f in fields) + ".")
        else:
            explanation = "; ".join(problems) + "."
            explanation = explanation[0].upper() + explanation[1:]
        return {"result": result, "explanation": explanation, "feedback": " ".join(fixes) if fixes else None,
                "failures": failures, "package": fact["package"] if fact else None, "fields": fields,
                "latency_ms": round((time.perf_counter() - start) * 1000, 2)}

    @staticmethod
    def _check(field: str, fact: dict[str, Any], answer: str) -> tuple[str, str, str]:
        if field == "fixed_version":
            expected = fact["fixed_version"]
            if has_version(answer, expected):
                return "ok", "", expected
            others = VERSION_RE.findall(answer)
            return ("wrong", ", ".join(others), expected) if others else ("missing", "", expected)
        if field == "affected_versions":
            expected = fact["affected_versions"]
            if all(has_version(answer, v) for v in range_versions(expected)):
                return "ok", "", expected
            others = VERSION_RE.findall(answer)
            return ("wrong", ", ".join(others), expected) if others else ("missing", "", expected)
        if field == "severity":
            expected = fact["severity"]
            text = re.sub(r"\bmoderate\b", "medium", answer, flags=re.I)
            found = [s for s in SEVERITIES if re.search(rf"\b{s}\b", text, re.I)]
            if expected in found:
                return "ok", "", expected
            return ("wrong", ", ".join(found), expected) if found else ("missing", "", expected)
        expected = fact["cve"]
        found = sorted({c.upper() for c in CVE_RE.findall(answer)})
        if expected in found:
            return "ok", "", expected
        return ("wrong", ", ".join(found), expected) if found else ("missing", "", expected)


# ----------------------------------------------------------------------------- the workflow


class SelfImprovingSystem:
    """Answer -> evaluate -> (revise once) loop, with optional lesson memory and lesson creation."""

    def __init__(self, repair: bool, lessons: LessonStore | None = None, learn: bool = False,
                 repeat_threshold: int = REPEAT_THRESHOLD, log: Any = None) -> None:
        self.answering = AnsweringAgent()
        self.evaluator = EvaluatorAgent()
        self.repair, self.lessons, self.learn = repair, lessons, learn
        self.repeat_threshold = repeat_threshold
        self.pattern_counts: Counter = Counter()
        self.pattern_status: dict[str, Counter] = {}
        self.log = log or (lambda *_a, **_k: None)

    def solve(self, item: dict[str, str], fault: str | None = None) -> dict[str, Any]:
        """Run one question through at most MAX_ATTEMPTS attempts and return the full trace."""

        question = item["question"]
        start = time.perf_counter()
        relevant = self.lessons.relevant(question) if self.lessons else []
        if relevant:
            self.lessons.mark_used(relevant)
            self.log("LESSONS LOADED", id=item["id"], lessons=[(x["lesson_id"], x["use_count"]) for x in relevant])
        attempts: list[dict[str, Any]] = []
        feedback = previous = None
        for number in range(1, MAX_ATTEMPTS + 1):
            answer = self.answering.answer(question, relevant, feedback=feedback, previous=previous,
                                           fault=fault if number == 1 else None)
            evaluation = self.evaluator.evaluate(question, answer["answer"])
            attempts.append({"attempt": number, **answer, "evaluation": evaluation})
            self.log("EVALUATED", id=item["id"], attempt=number, result=evaluation["result"],
                     explanation=evaluation["explanation"])
            if evaluation["result"] == "PASS" or not self.repair or number == MAX_ATTEMPTS:
                break  # stopping condition: PASS, no repair in this variant, or the second attempt is done
            feedback, previous = evaluation["feedback"], answer["answer"]
        created = self._learn(item, attempts[0]["evaluation"]) if self.learn else []
        final = attempts[-1]
        return {"id": item["id"], "question": question, "attempts": attempts, "n_attempts": len(attempts),
                "initial_result": attempts[0]["evaluation"]["result"], "final_result": final["evaluation"]["result"],
                "final_answer": final["answer"], "lessons_loaded": [x["lesson_id"] for x in relevant],
                "lessons_created": created, "latency_ms": round((time.perf_counter() - start) * 1000, 2)}

    def _learn(self, item: dict[str, str], evaluation: dict[str, Any]) -> list[str]:
        """Count failure patterns of the initial answer; create a lesson when one repeats."""

        created = []
        for failure in evaluation["failures"]:
            key = failure["pattern"]
            self.pattern_counts[key] += 1
            self.pattern_status.setdefault(key, Counter())[failure["status"]] += 1
            if self.pattern_counts[key] >= self.repeat_threshold and not self.lessons.has_pattern(key):
                lesson = self.lessons.add({**lesson_for(key, self.pattern_status[key]), "created_from": item["id"]})
                created.append(lesson["lesson_id"])
                self.log("LESSON CREATED", id=item["id"], lesson=lesson["lesson_id"], pattern=key,
                         seen=self.pattern_counts[key], failure_pattern=lesson["failure_pattern"])
        return created


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Correct / incorrect / average attempts / average latency for one variant run."""

    n = len(results)
    correct = sum(r["final_result"] == "PASS" for r in results)
    return {"questions": n, "correct": correct, "incorrect": n - correct,
            "initial_pass": sum(r["initial_result"] == "PASS" for r in results),
            "avg_attempts": round(sum(r["n_attempts"] for r in results) / n, 2),
            "avg_latency_ms": round(sum(r["latency_ms"] for r in results) / n, 1)}
