import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TriggerRunModal } from "./TriggerRunModal";
import { RunDetailPage } from "./RunDetailPage";
import { StepTimeline } from "./StepTimeline";
import { RouterProvider } from "../../router/Router";
import { AuthProvider } from "../../auth/AuthProvider";

describe("Workflow Runs Suite (P4-F01 to P4-F03)", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    vi.useRealTimers();
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("P4-F01: reuses the same Idempotency-Key across submission retries", async () => {
    let callCount = 0;
    const capturedKeys: (string | null)[] = [];

    global.fetch = vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
      callCount += 1;
      const headers = new Headers(init?.headers);
      capturedKeys.push(headers.get("Idempotency-Key"));

      if (callCount === 1) {
        // First submission fails
        return Promise.resolve({
          ok: false,
          status: 500,
          headers: new Headers({ "content-type": "application/problem+json" }),
          json: () =>
            Promise.resolve({
              code: "INTERNAL_ERROR",
              detail: "Transient server failure",
            }),
        });
      }

      // Second submission succeeds
      return Promise.resolve({
        ok: true,
        status: 202,
        headers: new Headers({ "content-type": "application/json" }),
        json: () =>
          Promise.resolve({
            run_id: "00000000-0000-0000-0000-000000000999",
            state: "QUEUED",
            workflow_id: "00000000-0000-0000-0000-000000000001",
            workflow_version: 1,
            version_id: "00000000-0000-0000-0000-000000000101",
            status_url: "/v1/runs/00000000-0000-0000-0000-000000000999",
            created_at: "2026-10-25T14:00:00Z",
          }),
      });
    });

    const handleSuccess = vi.fn();
    const handleClose = vi.fn();

    render(
      <TriggerRunModal
        workflowId="00000000-0000-0000-0000-000000000001"
        orgId="00000000-0000-0000-0000-000000000010"
        isOpen={true}
        onClose={handleClose}
        onSuccess={handleSuccess}
      />
    );

    const submitBtn = screen.getByTestId("btn-submit-trigger");
    const idempInput = screen.getByTestId("idempotency-key-input") as HTMLInputElement;
    const initialKey = idempInput.value;
    expect(initialKey).toBeTruthy();

    // 1st attempt: fails
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByTestId("trigger-error")).toHaveTextContent("Transient server failure");
    });

    // Verify key remains strictly identical
    expect(idempInput.value).toBe(initialKey);

    // 2nd attempt: succeeds
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(handleSuccess).toHaveBeenCalledWith("00000000-0000-0000-0000-000000000999");
    });

    expect(capturedKeys).toHaveLength(2);
    expect(capturedKeys[0]).toBe(initialKey);
    expect(capturedKeys[1]).toBe(initialKey);
  });

  it("P4-F02: polls while RUNNING and stops polling when SUCCEEDED", async () => {
    vi.useFakeTimers();
    let pollCount = 0;

    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/v1/organizations")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () => Promise.resolve({ items: [{ id: "org-1", my_role: "owner" }] }),
        });
      }
      if (url.includes("/steps")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () => Promise.resolve({ items: [] }),
        });
      }

      pollCount += 1;
      const state = pollCount >= 2 ? "SUCCEEDED" : "RUNNING";

      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: () =>
          Promise.resolve({
            id: "run-123",
            org_id: "org-1",
            workflow_id: "wf-1",
            workflow_version: 1,
            version_id: "v-1",
            state: state,
            trigger_kind: "manual",
            current_step_id: state === "SUCCEEDED" ? null : "step_a",
            started_at: "2026-10-25T14:00:00Z",
            finished_at: state === "SUCCEEDED" ? "2026-10-25T14:00:05Z" : null,
            created_at: "2026-10-25T14:00:00Z",
            inputs: {},
            outputs: state === "SUCCEEDED" ? { res: "ok" } : null,
            context: {},
            status_url: "/v1/runs/run-123",
          }),
      });
    });

    render(
      <AuthProvider>
        <RouterProvider>
          <RunDetailPage orgId="org-1" runId="run-123" />
        </RouterProvider>
      </AuthProvider>
    );

    // Initial fetch settles using Vitest's vi.waitFor
    await vi.waitFor(() => {
      expect(screen.getByTestId("run-state-badge")).toHaveTextContent("RUNNING");
    });
    const countAfterFirst = pollCount;

    // Advance 2000ms -> triggers next poll -> becomes SUCCEEDED
    await vi.advanceTimersByTimeAsync(2000);

    await vi.waitFor(() => {
      expect(screen.getByTestId("run-state-badge")).toHaveTextContent("SUCCEEDED");
    });
    const countAfterSecond = pollCount;
    expect(countAfterSecond).toBeGreaterThan(countAfterFirst);

    // Advance another 4000ms -> polling stops because state is terminal
    await vi.advanceTimersByTimeAsync(4000);
    expect(pollCount).toBe(countAfterSecond);

    vi.useRealTimers();
  });

  it("P4-F03: renders step attempts in chronological order", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/steps")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              items: [
                {
                  id: "att-1",
                  run_id: "run-100",
                  step_id: "step_first",
                  step_type: "set_data",
                  attempt_no: 1,
                  status: "SUCCEEDED",
                  output: { val: 10 },
                  started_at: "2026-10-25T14:00:01Z",
                  ended_at: "2026-10-25T14:00:02Z",
                  duration_ms: 12,
                },
                {
                  id: "att-2",
                  run_id: "run-100",
                  step_id: "step_second",
                  step_type: "condition",
                  attempt_no: 1,
                  status: "SUCCEEDED",
                  output: { selected_branch: "step_third" },
                  started_at: "2026-10-25T14:00:02Z",
                  ended_at: "2026-10-25T14:00:03Z",
                  duration_ms: 5,
                },
                {
                  id: "att-3",
                  run_id: "run-100",
                  step_id: "step_third",
                  step_type: "set_data",
                  attempt_no: 1,
                  status: "SUCCEEDED",
                  output: { done: true },
                  started_at: "2026-10-25T14:00:03Z",
                  ended_at: "2026-10-25T14:00:04Z",
                  duration_ms: 8,
                },
              ],
            }),
        });
      }

      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: () =>
          Promise.resolve({
            id: "run-100",
            org_id: "org-1",
            workflow_id: "wf-1",
            workflow_version: 1,
            version_id: "v-1",
            state: "SUCCEEDED",
            trigger_kind: "manual",
            current_step_id: null,
            started_at: "2026-10-25T14:00:01Z",
            finished_at: "2026-10-25T14:00:04Z",
            created_at: "2026-10-25T14:00:00Z",
            inputs: {},
            outputs: { done: true },
            context: {},
            status_url: "/v1/runs/run-100",
          }),
      });
    });

    render(
      <AuthProvider>
        <RouterProvider>
          <RunDetailPage orgId="org-1" runId="run-100" />
        </RouterProvider>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("step-attempt-step_first")).toBeInTheDocument();
      expect(screen.getByTestId("step-attempt-step_second")).toBeInTheDocument();
      expect(screen.getByTestId("step-attempt-step_third")).toBeInTheDocument();
    });

    expect(screen.getByTestId("step-output-step_first")).toHaveTextContent('"val": 10');
    expect(screen.getByTestId("step-output-step_third")).toHaveTextContent('"done": true');
  });

  it("P5-F01: renders multiple attempts for a retried step", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/steps")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              items: [
                {
                  id: "att-101",
                  run_id: "run-200",
                  step_id: "http_charge",
                  step_type: "http_request",
                  attempt_no: 1,
                  status: "FAILED",
                  error_code: "STEP_HTTP_ERROR",
                  error_detail: "503 Service Unavailable",
                  duration_ms: 105,
                  started_at: "2026-10-25T14:00:01Z",
                  ended_at: "2026-10-25T14:00:02Z",
                },
                {
                  id: "att-102",
                  run_id: "run-200",
                  step_id: "http_charge",
                  step_type: "http_request",
                  attempt_no: 2,
                  status: "SUCCEEDED",
                  output: { id: "ch_success_789" },
                  duration_ms: 45,
                  started_at: "2026-10-25T14:00:03Z",
                  ended_at: "2026-10-25T14:00:04Z",
                },
              ],
            }),
        });
      }

      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: () =>
          Promise.resolve({
            id: "run-200",
            org_id: "org-1",
            workflow_id: "wf-1",
            workflow_version: 1,
            version_id: "v-1",
            state: "SUCCEEDED",
            trigger_kind: "manual",
            current_step_id: null,
            started_at: "2026-10-25T14:00:01Z",
            finished_at: "2026-10-25T14:00:04Z",
            created_at: "2026-10-25T14:00:00Z",
            inputs: {},
            outputs: { id: "ch_success_789" },
            context: {},
            status_url: "/v1/runs/run-200",
          }),
      });
    });

    render(
      <AuthProvider>
        <RouterProvider>
          <RunDetailPage orgId="org-1" runId="run-200" />
        </RouterProvider>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("step-attempt-http_charge-1")).toBeInTheDocument();
      expect(screen.getByTestId("step-attempt-http_charge-2")).toBeInTheDocument();
    });

    // Check badges
    expect(screen.getByTestId("attempt-badge-http_charge-1")).toHaveTextContent(
      "Attempt #1 FAILED (STEP_HTTP_ERROR)"
    );
    expect(screen.getByTestId("attempt-badge-http_charge-2")).toHaveTextContent(
      "Attempt #2 SUCCEEDED"
    );

    // Check error detail for attempt 1
    expect(screen.getByTestId("attempt-error-http_charge-1")).toHaveTextContent(
      "503 Service Unavailable"
    );

    // Check output for attempt 2
    expect(screen.getByTestId("step-output-http_charge")).toHaveTextContent("ch_success_789");
  });

  it("P5-F02: Cancel and Retry buttons trigger respective endpoints and handle 409", async () => {
    let cancelCalled = false;
    let retryCalled = false;

    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes("/cancel") && init?.method === "POST") {
        cancelCalled = true;
        // First cancel attempt encounters 409 conflict
        return Promise.resolve({
          ok: false,
          status: 409,
          headers: new Headers({ "content-type": "application/problem+json" }),
          json: () =>
            Promise.resolve({
              code: "INVALID_STATE_TRANSITION",
              detail: "Run cannot be cancelled in its current state",
            }),
        });
      }

      if (url.includes("/retry") && init?.method === "POST") {
        retryCalled = true;
        return Promise.resolve({
          ok: true,
          status: 202,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              id: "run-300",
              org_id: "org-1",
              workflow_id: "wf-1",
              workflow_version: 1,
              version_id: "v-1",
              state: "QUEUED",
              trigger_kind: "manual",
              created_at: "2026-10-25T14:00:00Z",
              inputs: {},
              status_url: "/v1/runs/run-300",
            }),
        });
      }

      if (url.includes("/steps")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () => Promise.resolve({ items: [] }),
        });
      }

      const isFailed = url.includes("run-failed-400");
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: () =>
          Promise.resolve({
            id: isFailed ? "run-failed-400" : "run-300",
            org_id: "org-1",
            workflow_id: "wf-1",
            workflow_version: 1,
            version_id: "v-1",
            state: isFailed ? "FAILED" : "RUNNING",
            trigger_kind: "manual",
            created_at: "2026-10-25T14:00:00Z",
            inputs: {},
            status_url: isFailed ? "/v1/runs/run-failed-400" : "/v1/runs/run-300",
          }),
      });
    });

    render(
      <AuthProvider>
        <RouterProvider>
          <RunDetailPage orgId="org-1" runId="run-300" />
        </RouterProvider>
      </AuthProvider>
    );

    // 1. RUNNING state: cancel button visible
    await waitFor(() => {
      expect(screen.getByTestId("cancel-run-btn")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("retry-run-btn")).not.toBeInTheDocument();

    // Click cancel -> triggers POST and handles 409
    fireEvent.click(screen.getByTestId("cancel-run-btn"));
    await waitFor(() => {
      expect(cancelCalled).toBe(true);
      expect(screen.getByTestId("action-error")).toHaveTextContent(
        "Run cannot be cancelled in its current state"
      );
    });

    // 2. FAILED state: retry button visible
    render(
      <AuthProvider>
        <RouterProvider>
          <RunDetailPage orgId="org-1" runId="run-failed-400" />
        </RouterProvider>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("retry-run-btn")).toBeInTheDocument();
    });

    // Click retry -> triggers POST /retry
    fireEvent.click(screen.getByTestId("retry-run-btn"));
    await waitFor(() => {
      expect(retryCalled).toBe(true);
    });
  });

  it("P6-F01: renders classification label and confidence badge", () => {
    const steps = [
      {
        id: "att-1",
        run_id: "run-ai-1",
        org_id: "org-1",
        step_id: "classify_ticket",
        step_type: "llm_classify",
        attempt_no: 1,
        status: "SUCCEEDED",
        started_at: "2026-10-25T14:00:00Z",
        ended_at: "2026-10-25T14:00:01Z",
        duration_ms: 320,
        epoch: 1,
        output: {
          label: "billing",
          confidence: 0.95,
        },
      },
    ];

    render(<StepTimeline steps={steps} />);

    expect(screen.getByTestId("ai-step-badge")).toBeInTheDocument();
    expect(screen.getByTestId("ai-classify-label")).toHaveTextContent("Label: billing");
    expect(screen.getByTestId("ai-classify-confidence")).toHaveTextContent("Confidence: 95%");
    expect(screen.getByText(/Model: openrouter\/free/)).toBeInTheDocument();
    expect(screen.getByText(/Latency: 320 ms/)).toBeInTheDocument();
  });

  it("P6-F02: displays LLM_INVALID_OUTPUT failure state clearly", () => {
    const steps = [
      {
        id: "att-2",
        run_id: "run-ai-2",
        org_id: "org-1",
        step_id: "classify_ticket",
        step_type: "llm_classify",
        attempt_no: 2,
        status: "FAILED",
        error_code: "LLM_INVALID_OUTPUT",
        error_detail: "Schema validation failed after 2 attempts: missing required field 'label'",
        started_at: "2026-10-25T14:00:00Z",
        ended_at: "2026-10-25T14:00:01Z",
        duration_ms: 210,
        epoch: 1,
      },
    ];

    render(<StepTimeline steps={steps} />);

    expect(screen.getByTestId("ai-step-badge")).toBeInTheDocument();
    expect(screen.getByTestId("ai-invalid-output")).toBeInTheDocument();
    expect(screen.getByTestId("ai-invalid-output")).toHaveTextContent("LLM_INVALID_OUTPUT");
    expect(screen.getByTestId("ai-invalid-output")).toHaveTextContent("missing required field 'label'");
  });

  it("P7-F03: ApprovalBanner appears on WAITING_APPROVAL run", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/v1/runs/run-approval-1/steps")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () => Promise.resolve({ items: [] }),
        });
      }
      if (url.includes("/v1/runs/run-approval-1")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              id: "run-approval-1",
              org_id: "org-1",
              workflow_id: "wf-1",
              workflow_version: 1,
              state: "WAITING_APPROVAL",
              trigger_kind: "manual",
              started_at: "2026-10-25T14:00:00Z",
              inputs: {},
              context: {},
            }),
        });
      }
      if (url.includes("/v1/organizations/org-1/approvals")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              items: [
                {
                  id: "app-1",
                  org_id: "org-1",
                  run_id: "run-approval-1",
                  step_id: "triage_gate",
                  version_id: "ver-1",
                  assigned_role: "reviewer",
                  state: "PENDING",
                  summary: "Approve high-value refund",
                  expires_at: "2099-01-01T00:00:00Z",
                  created_at: "2026-10-25T14:00:00Z",
                },
              ],
            }),
        });
      }
      if (url.includes("/v1/organizations")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              items: [{ id: "org-1", name: "Dev Org", slug: "dev-org", my_role: "reviewer" }],
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: () => Promise.resolve({}),
      });
    });

    render(
      <RouterProvider initialPath="/orgs/org-1/runs/run-approval-1">
        <AuthProvider>
          <RunDetailPage orgId="org-1" runId="run-approval-1" />
        </AuthProvider>
      </RouterProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("approval-banner")).toBeInTheDocument();
    });

    expect(screen.getByTestId("approval-banner-summary")).toHaveTextContent("Approve high-value refund");
    expect(screen.getByTestId("approval-step-id")).toHaveTextContent("triage_gate");
    expect(screen.getByTestId("approval-assigned-role")).toHaveTextContent("reviewer");
    expect(screen.getByTestId("approve-btn")).toBeEnabled();
    expect(screen.getByTestId("reject-btn")).toBeEnabled();
  });
});
