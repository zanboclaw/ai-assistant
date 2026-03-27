const runtime = window.DashboardRuntime || {};

function buildHeaders(extraHeaders = {}) {
  const actorName = window.localStorage.getItem("ai-assistant-actor") || "local_admin";
  return {
    "Content-Type": "application/json",
    "X-Actor-Name": actorName,
    ...extraHeaders,
  };
}

export async function apiRequest(path, options = {}) {
  const bases = runtime.resolveApiBaseCandidates ? runtime.resolveApiBaseCandidates() : [window.location.origin];
  const requestOptions = {
    method: options.method || "GET",
    headers: buildHeaders(options.headers),
  };
  if (options.body !== undefined) {
    requestOptions.body = typeof options.body === "string" ? options.body : JSON.stringify(options.body);
  }

  let lastError = null;
  for (const base of bases) {
    try {
      const response = await fetch(`${base}${path}`, requestOptions);
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(`${response.status} ${detail}`);
      }
      const contentType = response.headers.get("content-type") || "";
      return contentType.includes("application/json") ? response.json() : response.text();
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("request failed");
}

