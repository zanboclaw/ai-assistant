from apps.worker.bootstrap.runtime_container import WorkerRuntimeContainer


def test_worker_runtime_container_exposes_runtime_entrypoints_only():
    container = WorkerRuntimeContainer()

    assert sorted(container) == ["main", "process_task"]
    assert callable(container["main"])
    assert callable(container["process_task"])
