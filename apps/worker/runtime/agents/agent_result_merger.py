from __future__ import annotations


def merge_agent_results(results: list[dict]) -> dict:
    return {
        "agent_results": list(results),
        "result_count": len(results),
    }

