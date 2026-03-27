from core.contracts.session_contracts import SessionContract


def test_session_contract_keeps_state_and_memories():
    session = SessionContract(session_id=8, title="发布会话", state={"status": "healthy"}, memories=[{"title": "发布前检查"}])

    assert session.session_id == 8
    assert session.state["status"] == "healthy"
    assert session.memories[0]["title"] == "发布前检查"

