import { apiRequest } from "../../app/api_client.js";

export function fetchVersion() {
  return apiRequest("/version");
}

