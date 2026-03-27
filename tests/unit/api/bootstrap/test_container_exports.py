from apps.api.bootstrap.container import APIContainer
from apps.api.bootstrap.container_exports import API_CONTAINER_EXPORTS


def test_api_container_exposes_explicit_whitelist_only():
    container = APIContainer()

    assert len(container) == len(API_CONTAINER_EXPORTS)
    assert "get_conn" in container
    assert "require_actor_permission" in container
    assert "serialize_session_row" in container
    assert "__name__" not in container
    assert "__builtins__" not in container
