import React, { useState, useEffect } from "react";
import { apiFetch } from "../../api/client";
import { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

type RunResponse = components["schemas"]["RunResponse"];

function generateUUIDv7(): string {
  const now = Date.now();
  const hexTime = now.toString(16).padStart(12, "0");
  const randBytes = crypto.getRandomValues(new Uint8Array(10));
  // version 7 (0x7)
  randBytes[0] = (randBytes[0] & 0x0f) | 0x70;
  // variant 1 (0x8)
  randBytes[2] = (randBytes[2] & 0x3f) | 0x80;
  const hexRand = Array.from(randBytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hexTime.slice(0, 8)}-${hexTime.slice(8, 12)}-${hexRand.slice(0, 4)}-${hexRand.slice(4, 8)}-${hexRand.slice(8)}`;
}

interface TriggerRunModalProps {
  workflowId: string;
  orgId: string;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (runId: string) => void;
}

export function TriggerRunModal({
  workflowId,
  isOpen,
  onClose,
  onSuccess,
}: TriggerRunModalProps) {
  const [inputsJson, setInputsJson] = useState("{\n  \n}");
  const [idempotencyKey, setIdempotencyKey] = useState<string>("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Generate a fresh idempotency key only when modal opens
  useEffect(() => {
    if (isOpen) {
      setIdempotencyKey(generateUUIDv7());
      setError(null);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    let parsedInputs: Record<string, unknown>;
    try {
      parsedInputs = JSON.parse(inputsJson || "{}");
    } catch {
      setError("Inputs must be valid JSON");
      return;
    }

    try {
      setIsSubmitting(true);
      const res = await apiFetch<RunResponse>(`/v1/workflows/${workflowId}/runs`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        },
        body: JSON.stringify({
          inputs: parsedInputs,
        }),
      });

      onSuccess(res.run_id);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.detail || err.message);
      } else {
        setError("Failed to trigger workflow run");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      data-testid="trigger-run-modal-backdrop"
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: "rgba(0, 0, 0, 0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div
        data-testid="trigger-run-modal"
        style={{
          background: "#fff",
          borderRadius: "8px",
          padding: "24px",
          width: "480px",
          maxWidth: "90%",
          boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.1)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "16px" }}>
          <h2 style={{ margin: 0, fontSize: "18px", fontWeight: "600" }}>Trigger Workflow Run</h2>
          <button
            data-testid="btn-close-modal"
            onClick={onClose}
            style={{ border: "none", background: "none", fontSize: "18px", cursor: "pointer" }}
          >
            ✕
          </button>
        </div>

        {error && (
          <div
            data-testid="trigger-error"
            style={{
              padding: "10px",
              background: "#fee2e2",
              color: "#b91c1c",
              borderRadius: "4px",
              fontSize: "13px",
              marginBottom: "16px",
            }}
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: "12px" }}>
            <label
              htmlFor="idempotency-key"
              style={{ display: "block", fontSize: "12px", fontWeight: "500", color: "#64748b", marginBottom: "4px" }}
            >
              Idempotency Key
            </label>
            <input
              id="idempotency-key"
              data-testid="idempotency-key-input"
              type="text"
              readOnly
              value={idempotencyKey}
              style={{
                width: "100%",
                padding: "8px",
                fontSize: "12px",
                fontFamily: "monospace",
                borderRadius: "4px",
                border: "1px solid #cbd5e1",
                background: "#f8fafc",
                boxSizing: "border-box",
              }}
            />
          </div>

          <div style={{ marginBottom: "16px" }}>
            <label
              htmlFor="run-inputs"
              style={{ display: "block", fontSize: "13px", fontWeight: "500", color: "#334155", marginBottom: "4px" }}
            >
              Workflow Inputs (JSON)
            </label>
            <textarea
              id="run-inputs"
              data-testid="run-inputs-textarea"
              rows={6}
              value={inputsJson}
              onChange={(e) => setInputsJson(e.target.value)}
              style={{
                width: "100%",
                padding: "8px",
                fontSize: "13px",
                fontFamily: "monospace",
                borderRadius: "4px",
                border: "1px solid #cbd5e1",
                boxSizing: "border-box",
              }}
            />
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
            <button
              type="button"
              data-testid="btn-cancel-trigger"
              onClick={onClose}
              disabled={isSubmitting}
              style={{
                padding: "8px 16px",
                background: "#fff",
                border: "1px solid #cbd5e1",
                borderRadius: "4px",
                cursor: "pointer",
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              data-testid="btn-submit-trigger"
              disabled={isSubmitting}
              style={{
                padding: "8px 16px",
                background: "#2563eb",
                color: "#fff",
                border: "none",
                borderRadius: "4px",
                cursor: isSubmitting ? "not-allowed" : "pointer",
                fontWeight: "500",
              }}
            >
              {isSubmitting ? "Triggering..." : "Run Workflow"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
