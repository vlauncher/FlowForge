import React, { useState } from "react";
import { useAuth } from "../../auth/AuthProvider";
import { useRouter } from "../../router/Router";
import { ApiError } from "../../api/errors";

export function LoginPage() {
  const { login } = useAuth();
  const { navigate, redirectAfterLogin, setRedirectAfterLogin } = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      await login({ email, password });
      const target = redirectAfterLogin || "/orgs";
      setRedirectAfterLogin(null);
      navigate(target);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.status === 401 || err.code === "INVALID_CREDENTIALS") {
          setError("Invalid email or password");
        } else {
          setError(err.detail || err.message || "Login failed");
        }
      } else {
        setError("An unexpected error occurred");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div style={{ maxWidth: "400px", margin: "60px auto", padding: "24px", border: "1px solid #e2e8f0", borderRadius: "8px" }}>
      <h2 style={{ marginBottom: "20px" }}>Log In</h2>

      {error && (
        <div
          data-testid="login-error"
          style={{ padding: "10px", marginBottom: "16px", background: "#fee2e2", color: "#b91c1c", borderRadius: "4px" }}
        >
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: "16px" }}>
          <label htmlFor="login-email" style={{ display: "block", marginBottom: "6px", fontSize: "14px" }}>
            Email
          </label>
          <input
            id="login-email"
            data-testid="login-email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid #cbd5e1" }}
          />
        </div>

        <div style={{ marginBottom: "20px" }}>
          <label htmlFor="login-password" style={{ display: "block", marginBottom: "6px", fontSize: "14px" }}>
            Password
          </label>
          <input
            id="login-password"
            data-testid="login-password"
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid #cbd5e1" }}
          />
        </div>

        <button
          type="submit"
          data-testid="login-submit"
          disabled={isSubmitting}
          style={{
            width: "100%",
            padding: "10px",
            background: isSubmitting ? "#93c5fd" : "#3b82f6",
            color: "#fff",
            border: "none",
            borderRadius: "4px",
            cursor: isSubmitting ? "not-allowed" : "pointer",
            fontWeight: "bold",
          }}
        >
          {isSubmitting ? "Logging in..." : "Log In"}
        </button>
      </form>

      <p style={{ marginTop: "16px", fontSize: "14px", textAlign: "center" }}>
        Don't have an account?{" "}
        <button
          data-testid="link-signup"
          onClick={() => navigate("/signup")}
          style={{ background: "none", border: "none", color: "#3b82f6", cursor: "pointer", textDecoration: "underline" }}
        >
          Sign up
        </button>
      </p>
    </div>
  );
}
