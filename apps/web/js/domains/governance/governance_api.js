import { apiRequest } from "../../app/api_client.js";

export function fetchGovernanceSnapshot() {
  return Promise.all([
    apiRequest("/risk-policies"),
    apiRequest("/tools"),
    apiRequest("/model-routes"),
  ]);
}

