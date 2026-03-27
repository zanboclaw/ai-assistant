from core.contracts.governance_contracts import ChangeRequestContract, GovernanceDecisionContract
from core.shared.enums import ChangeRequestStatus


def test_governance_contracts_capture_status_and_decision():
    decision = GovernanceDecisionContract(actor_name="local_admin", permission="admin", approved=True)
    change_request = ChangeRequestContract(change_request_id=7, target_type="model_route", target_name="planner", status=ChangeRequestStatus.APPROVED)

    assert decision.approved is True
    assert change_request.status == ChangeRequestStatus.APPROVED

