from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.long_term_memory import create_long_term_memory_table


MIGRATION_ID = "0002_long_term_memory"
DESCRIPTION = "Create long_term_memories as an explicit migration-managed table."


def apply(cur) -> None:
    create_long_term_memory_table(cur)
