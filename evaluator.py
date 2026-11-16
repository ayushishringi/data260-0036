"""HW10 Part 2 evaluator agent process. Usage: python evaluator.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.evaluator import run_evaluator  # noqa: E402

if __name__ == "__main__":
    run_evaluator()
