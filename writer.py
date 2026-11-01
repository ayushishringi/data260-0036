"""HW8 Part 2 writer agent process. Usage: python writer.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.agent_pipeline import main  # noqa: E402

if __name__ == "__main__":
    main("writer")
