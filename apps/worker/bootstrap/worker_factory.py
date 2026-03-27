from __future__ import annotations

from functools import lru_cache

from apps.worker.bootstrap.runtime_container import WorkerRuntimeContainer, build_runtime_container


@lru_cache(maxsize=1)
def get_worker_container() -> WorkerRuntimeContainer:
    return build_runtime_container()


def process_task(task: dict, claim_heartbeat=None):
    container = get_worker_container()
    return container["process_task"](task, claim_heartbeat)


def main():
    container = get_worker_container()
    return container["main"]()

