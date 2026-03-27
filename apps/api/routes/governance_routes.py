from __future__ import annotations

from fastapi import FastAPI


def register_governance_routes(*, app: FastAPI, container) -> None:
    app.include_router(
        container["register_governance_routes"](
            get_conn=lambda: container["get_conn"](),
            require_actor_permission=lambda cur, actor_name, permission: container["require_actor_permission"](cur, actor_name, permission),
            seed_default_risk_policies=lambda cur: container["seed_default_risk_policies"](cur),
            deserialize_policy_row=container["deserialize_policy_row"],
            seed_default_tool_registry=lambda cur: container["seed_default_tool_registry"](cur),
            serialize_tool_registry_row=container["serialize_tool_registry_row"],
            seed_default_model_providers=lambda cur: container["seed_default_model_providers"](cur),
            seed_default_model_routes=lambda cur: container["seed_default_model_routes"](cur),
            serialize_model_route_row=container["serialize_model_route_row"],
            serialize_model_provider_row=container["serialize_model_provider_row"],
            seed_default_access_actors=lambda cur: container["seed_default_access_actors"](cur),
            seed_default_access_quotas=lambda cur: container["seed_default_access_quotas"](cur),
            serialize_access_actor_row=container["serialize_access_actor_row"],
            serialize_access_quota_row=container["serialize_access_quota_row"],
            parse_maybe_json=container["parse_maybe_json"],
            validate_policy_value=container["validate_policy_value"],
            update_risk_policy_entry=container["update_risk_policy_entry"],
            update_tool_registry_entry=container["update_tool_registry_entry"],
            update_model_route_entry=container["update_model_route_entry"],
            upsert_model_provider_entry=container["upsert_model_provider_entry"],
            upsert_access_actor=container["upsert_access_actor"],
            upsert_access_quota=container["upsert_access_quota"],
            upsert_default_access_quota=container["upsert_default_access_quota"],
            insert_audit_log=container["insert_audit_log"],
            enforce_change_gate_for_direct_update=container["enforce_change_gate_for_direct_update"],
            ensure_audit_logs_table=container["ensure_audit_logs_table"],
            access_role_permissions=container["ACCESS_ROLE_PERMISSIONS"],
            step_request_protocol_version=container["STEP_REQUEST_PROTOCOL_VERSION"],
            step_execution_request_fields=container["STEP_EXECUTION_REQUEST_FIELDS"],
            enriched_step_execution_request_extra_fields=container["ENRICHED_STEP_EXECUTION_REQUEST_EXTRA_FIELDS"],
            multi_agent_protocol_version=container["MULTI_AGENT_PROTOCOL_VERSION"],
            auto_stage5_postrun_enabled=container["AUTO_STAGE5_POSTRUN_ENABLED"],
            get_runtime_version_metadata=container["get_runtime_version_metadata"],
            logger=container["logger"],
        )
    )
