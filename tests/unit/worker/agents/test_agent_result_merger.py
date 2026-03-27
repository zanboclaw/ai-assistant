from apps.worker.runtime.agents.agent_result_merger import merge_agent_results


def test_agent_result_merger_returns_count():
    merged = merge_agent_results([{"role": "planner"}, {"role": "reviewer"}])

    assert merged["result_count"] == 2

