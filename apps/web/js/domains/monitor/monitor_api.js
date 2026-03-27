import { apiRequest } from "../../app/api_client.js";

export function fetchMonitorOverview() {
  return apiRequest("/monitor/overview");
}

