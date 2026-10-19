"""Unit tests for HW6 file-based memory consolidation."""

from __future__ import annotations

import unittest

from backend.hw6_file_memory import audit_resolutions, consolidate_memory_text


SAMPLE = """# Durable Memory
- [2026-09-01] port: 8036
- [2026-10-01] api_framework: FastAPI
- [2026-10-02] api_framework: fastapi
- [2026-10-14] port: 8000
- The user prefers short answers.
- The user prefers short answers.
"""


class ConsolidateMemoryTextTests(unittest.TestCase):
    def test_merges_duplicates_case_insensitively(self) -> None:
        text, stats = consolidate_memory_text(SAMPLE)
        self.assertEqual(stats["duplicates_merged"], 2)
        self.assertIn("api_framework: FastAPI (seen 2x)", text)
        self.assertIn("The user prefers short answers. (seen 2x)", text)

    def test_contradiction_resolved_and_superseded_value_kept(self) -> None:
        text, stats = consolidate_memory_text(SAMPLE)
        self.assertEqual(stats["contradictions_resolved"], 1)
        self.assertIn("## Resolved contradictions", text)
        self.assertIn('superseded "8036"', text)

    def test_reconsolidation_is_stable(self) -> None:
        once, _ = consolidate_memory_text(SAMPLE)
        twice, stats = consolidate_memory_text(once)
        self.assertEqual(stats["duplicates_merged"], 0)
        self.assertEqual(stats["contradictions_resolved"], 0)
        self.assertEqual(once.split("-->", 1)[1], twice.split("-->", 1)[1])

    def test_fact_appended_after_resolutions_is_still_a_fact(self) -> None:
        once, _ = consolidate_memory_text(SAMPLE)
        text, stats = consolidate_memory_text(once + "- [2026-10-18] port: 8036\n")
        self.assertEqual(stats["contradictions_resolved"], 1)
        self.assertIn('port: kept "8036" [2026-10-18]; superseded "8000"', text)


class AuditResolutionsTests(unittest.TestCase):
    def test_flags_resolution_that_disagrees_with_ground_truth(self) -> None:
        _, stats = consolidate_memory_text(SAMPLE)
        incorrect = audit_resolutions(stats["resolutions"], {"port": "8036"})
        self.assertEqual(incorrect, [{"key": "port", "kept": "8000", "expected": "8036"}])

    def test_correct_or_unknown_keys_are_not_flagged(self) -> None:
        resolutions = [{"key": "ollama_model", "kept": "qwen3:4b"}, {"key": "other", "kept": "x"}]
        self.assertEqual(audit_resolutions(resolutions, {"ollama_model": "QWEN3:4B"}), [])


if __name__ == "__main__":
    unittest.main()
