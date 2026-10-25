import { describe, it, expect, vi, afterEach } from "vitest";
import { apiFetch } from "./client";
import { ApiError } from "./errors";

describe("apiFetch & ApiError handling (P1-F01, P1-F04)", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("P1-F01: parses ApiError from application/problem+json response", async () => {
    const mockProblemDetails = {
      type: "https://flowforge.dev/errors/VALIDATION_ERROR",
      title: "Validation Error",
      status: 422,
      detail: "Invalid parameters provided",
      instance: "/api/v1/test",
      code: "VALIDATION_ERROR",
      request_id: "req-12345",
      errors: [{ field: "name", message: "Field is required" }],
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      headers: new Headers({
        "content-type": "application/problem+json",
        "x-request-id": "req-12345",
      }),
      json: async () => mockProblemDetails,
    } as unknown as Response);

    await expect(apiFetch("/api/v1/test")).rejects.toThrow(ApiError);

    try {
      await apiFetch("/api/v1/test");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(422);
      expect(apiErr.code).toBe("VALIDATION_ERROR");
      expect(apiErr.detail).toBe("Invalid parameters provided");
      expect(apiErr.requestId).toBe("req-12345");
      expect(apiErr.errors).toEqual([{ field: "name", message: "Field is required" }]);
    }
  });

  it("P1-F04: handles network failure with generic NETWORK_OR_UNKNOWN error", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("Failed to fetch"));

    try {
      await apiFetch("/api/v1/health");
      expect.fail("Should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(0);
      expect(apiErr.code).toBe("NETWORK_OR_UNKNOWN");
      expect(apiErr.detail).toBe("Failed to fetch");
    }
  });

  it("returns json data on 200 ok", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ status: "ok" }),
    } as unknown as Response);

    const res = await apiFetch<{ status: string }>("/health");
    expect(res).toEqual({ status: "ok" });
  });

  it("returns undefined on 204 No Content", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      headers: new Headers(),
    } as unknown as Response);

    const res = await apiFetch<void>("/no-content");
    expect(res).toBeUndefined();
  });
});
