import React, { useState } from "react";
import { useAuth } from "../../auth/AuthProvider";
import { useRouter } from "../../router/Router";
import { ApiError } from "../../api/errors";
import { AuthLayout } from "../../components/AuthLayout";

export function SignupPage() {
  const { signup } = useAuth();
  const { navigate, redirectAfterLogin, setRedirectAfterLogin } = useRouter();

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const [fieldErrors, setFieldErrors] = useState<{
    displayName?: string;
    email?: string;
    password?: string;
    general?: string;
  }>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const errors: typeof fieldErrors = {};

    if (!displayName.trim()) {
      errors.displayName = "Display name is required";
    }

    if (!email.includes("@") || !email.includes(".")) {
      errors.email = "Please enter a valid email address";
    }

    if (password.length < 12) {
      errors.password = "Password must be at least 12 characters";
    }

    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }

    setFieldErrors({});
    setIsSubmitting(true);

    try {
      await signup({
        display_name: displayName.trim(),
        email: email.trim(),
        password,
      });
      const target = redirectAfterLogin || "/orgs";
      setRedirectAfterLogin(null);
      navigate(target);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.status === 409 || err.code === "EMAIL_TAKEN") {
          setFieldErrors({ email: "Email is already registered" });
        } else if (err.status === 422 && err.errors && err.errors.length > 0) {
          const mapped: typeof fieldErrors = {};
          for (const fe of err.errors) {
            const field = fe.field?.toLowerCase();
            if (field?.includes("email")) {
              mapped.email = fe.message;
            } else if (field?.includes("password")) {
              mapped.password = fe.message;
            } else if (field?.includes("name") || field?.includes("display")) {
              mapped.displayName = fe.message;
            } else {
              mapped.general = fe.message;
            }
          }
          setFieldErrors(mapped);
        } else {
          setFieldErrors({ general: err.detail || err.message || "Signup failed" });
        }
      } else {
        setFieldErrors({ general: "An unexpected error occurred" });
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthLayout title="Create an Account" subtitle="Spin up a workspace in under a minute.">

      {fieldErrors.general && (
        <div
          data-testid="signup-error"
          style={{ padding: "10px", marginBottom: "16px", background: "var(--danger-bg)", color: "var(--danger-fg)", borderRadius: "4px" }}
        >
          {fieldErrors.general}
        </div>
      )}

      <form onSubmit={handleSubmit} noValidate>
        <div style={{ marginBottom: "16px" }}>
          <label htmlFor="signup-name" style={{ display: "block", marginBottom: "6px", fontSize: "14px" }}>
            Display Name
          </label>
          <input
            id="signup-name"
            data-testid="signup-name"
            type="text"
            required
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)" }}
          />
          {fieldErrors.displayName && (
            <p data-testid="error-name" style={{ color: "var(--danger-fg)", fontSize: "12px", marginTop: "4px" }}>
              {fieldErrors.displayName}
            </p>
          )}
        </div>

        <div style={{ marginBottom: "16px" }}>
          <label htmlFor="signup-email" style={{ display: "block", marginBottom: "6px", fontSize: "14px" }}>
            Email
          </label>
          <input
            id="signup-email"
            data-testid="signup-email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)" }}
          />
          {fieldErrors.email && (
            <p data-testid="error-email" style={{ color: "var(--danger-fg)", fontSize: "12px", marginTop: "4px" }}>
              {fieldErrors.email}
            </p>
          )}
        </div>

        <div style={{ marginBottom: "20px" }}>
          <label htmlFor="signup-password" style={{ display: "block", marginBottom: "6px", fontSize: "14px" }}>
            Password (min 12 characters)
          </label>
          <input
            id="signup-password"
            data-testid="signup-password"
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)" }}
          />
          {fieldErrors.password && (
            <p data-testid="error-password" style={{ color: "var(--danger-fg)", fontSize: "12px", marginTop: "4px" }}>
              {fieldErrors.password}
            </p>
          )}
        </div>

        <button
          type="submit"
          data-testid="signup-submit"
          disabled={isSubmitting}
          style={{
            width: "100%",
            padding: "10px",
            background: isSubmitting ? "var(--primary-dim)" : "var(--grad-primary)",
            color: "#fff",
            border: "none",
            borderRadius: "4px",
            cursor: isSubmitting ? "not-allowed" : "pointer",
            fontWeight: "bold",
          }}
        >
          {isSubmitting ? "Creating account..." : "Sign Up"}
        </button>
      </form>

      <p style={{ marginTop: "16px", fontSize: "14px", textAlign: "center" }}>
        Already have an account?{" "}
        <button
          data-testid="link-login"
          onClick={() => navigate("/login")}
          style={{ background: "none", border: "none", color: "var(--link)", cursor: "pointer", textDecoration: "underline" }}
        >
          Log in
        </button>
      </p>
    </AuthLayout>
  );
}
