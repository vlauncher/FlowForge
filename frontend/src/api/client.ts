import { ApiError, ProblemDetailsPayload } from "./errors";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

let inMemoryAccessToken: string | null = null;
let unauthenticatedCallback: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  inMemoryAccessToken = token;
}

export function getAccessToken(): string | null {
  return inMemoryAccessToken;
}

export function setOnUnauthenticated(callback: (() => void) | null): void {
  unauthenticatedCallback = callback;
}

export interface ApiFetchOptions extends RequestInit {
  _isRetry?: boolean;
}

export async function apiFetch<T>(path: string, init?: ApiFetchOptions): Promise<T> {
  const url = `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
  const headers = new Headers(init?.headers);

  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }

  if (inMemoryAccessToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${inMemoryAccessToken}`);
  }

  // Include credentials for cookies (e.g. ff_refresh)
  const credentials = init?.credentials ?? "include";

  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers,
      credentials,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Network request failed";
    throw new ApiError(0, "NETWORK_OR_UNKNOWN", message);
  }

  const requestIdHeader = response.headers.get("x-request-id") || undefined;

  // Interceptor: on 401, retry once via /v1/auth/refresh
  if (
    response.status === 401 &&
    !init?._isRetry &&
    !path.includes("/v1/auth/refresh") &&
    !path.includes("/v1/auth/login")
  ) {
    try {
      const refreshUrl = `${API_BASE_URL}/v1/auth/refresh`;
      const refreshRes = await fetch(refreshUrl, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "X-FlowForge-CSRF": "1",
        },
        credentials: "include",
      });

      if (refreshRes.ok) {
        const refreshData = (await refreshRes.json()) as { access_token: string };
        setAccessToken(refreshData.access_token);
        // Replay original request with new access token and marked as retry
        return apiFetch<T>(path, {
          ...init,
          _isRetry: true,
          headers: {
            ...Object.fromEntries(headers.entries()),
            Authorization: `Bearer ${refreshData.access_token}`,
          },
        });
      } else {
        setAccessToken(null);
        if (unauthenticatedCallback) {
          unauthenticatedCallback();
        }
      }
    } catch {
      setAccessToken(null);
      if (unauthenticatedCallback) {
        unauthenticatedCallback();
      }
    }
  }

  if (!response.ok) {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/problem+json") || contentType.includes("application/json")) {
      try {
        const body = (await response.json()) as ProblemDetailsPayload;
        throw new ApiError(
          response.status,
          body.code || "UNKNOWN_ERROR",
          body.detail,
          body.request_id || requestIdHeader,
          body.errors
        );
      } catch (err: unknown) {
        if (err instanceof ApiError) throw err;
        throw new ApiError(
          response.status,
          "NETWORK_OR_UNKNOWN",
          `HTTP ${response.status}: Failed to parse error response`,
          requestIdHeader
        );
      }
    }

    const text = await response.text().catch(() => "");
    throw new ApiError(
      response.status,
      "NETWORK_OR_UNKNOWN",
      text || `HTTP ${response.status}`,
      requestIdHeader
    );
  }

  if (response.status === 204) {
    return undefined as unknown as T;
  }

  return response.json() as Promise<T>;
}
