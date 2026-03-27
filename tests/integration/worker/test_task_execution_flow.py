from apps.worker.bootstrap import worker_factory


def test_worker_factory_process_task_delegates(monkeypatch):
    class FakeContainer(dict):
        pass

    calls = []
    fake_container = FakeContainer(process_task=lambda task, claim_heartbeat=None: calls.append((task, claim_heartbeat)))
    monkeypatch.setattr(worker_factory, "get_worker_container", lambda: fake_container)

    worker_factory.process_task({"id": 9}, claim_heartbeat="hb")

    assert calls == [({"id": 9}, "hb")]

