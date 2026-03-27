import { apiRequest } from "../../app/api_client.js";

export function fetchSessions() {
  return apiRequest("/sessions");
}

