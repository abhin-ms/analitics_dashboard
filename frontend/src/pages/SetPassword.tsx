import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { Lock, AlertCircle, Loader2, ArrowLeft } from "lucide-react";

export default function SetPassword() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");

  const mutation = useMutation({
    mutationFn: (data: { token: string; new_password: string }) =>
      api.post("/auth/set-password", data),
    onSuccess: () => navigate("/login"),
    onError: (err: any) =>
      setError(err.message || "Failed to reset password"),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (password !== confirm) {
      setError("Passwords don't match");
      return;
    }
    if (password.length < 6) {
      setError("Password must be at least 6 characters");
      return;
    }
    mutation.mutate({ token: token || "", new_password: password });
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--auth-page-bg)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px 16px",
        position: "relative",
      }}
    >
      {/* Background decorative blobs */}
      <div style={{ position: "fixed", inset: 0, overflow: "hidden", pointerEvents: "none", zIndex: 0 }}>
        <div style={{ position: "absolute", top: "-20%", left: "-20%", width: "60%", height: "60%", background: "radial-gradient(circle, rgba(59,130,246,0.08) 0%, transparent 70%)", borderRadius: "50%" }} />
        <div style={{ position: "absolute", bottom: "-20%", right: "-20%", width: "60%", height: "60%", background: "radial-gradient(circle, rgba(168,85,247,0.08) 0%, transparent 70%)", borderRadius: "50%" }} />
      </div>

      <div style={{ position: "relative", width: "100%", maxWidth: "480px", margin: "0 auto", zIndex: 10 }}>
        {/* Logo Section */}
        <div style={{ textAlign: "center", marginBottom: "40px" }}>
          <div style={{ display: "inline-block", position: "relative", marginBottom: "20px" }}>
            <div
              style={{
                position: "absolute",
                inset: "-4px",
                background: "linear-gradient(135deg, #1f6feb, #60a5fa)",
                borderRadius: "20px",
                filter: "blur(16px)",
                opacity: 0.6,
              }}
            />
            <img
              src="/logo-mark.png"
              alt="Break Protection"
              width={72}
              height={72}
              style={{ position: "relative", display: "block", borderRadius: "16px" }}
            />
          </div>
          <h1
            style={{
              fontSize: "32px",
              fontWeight: 700,
              background: "var(--auth-title-grad)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              marginBottom: "8px",
              lineHeight: 1.2,
            }}
          >
            Create New Password
          </h1>
          <p style={{ color: "var(--auth-muted)", fontSize: "14px" }}>
            Set a strong password for your account
          </p>
        </div>

        {/* Form Card */}
        <div
          style={{
            background: "var(--auth-card-bg)",
            border: "1px solid var(--auth-card-border)",
            borderRadius: "24px",
            padding: "48px 40px",
            backdropFilter: "blur(20px)",
            boxShadow: "var(--auth-card-shadow)",
          }}
        >
          <form onSubmit={handleSubmit}>
            {/* New Password Field */}
            <div style={{ marginBottom: "28px" }}>
              <label
                htmlFor="set-password"
                style={{
                  display: "block",
                  fontSize: "14px",
                  fontWeight: 600,
                  color: "var(--auth-label)",
                  marginBottom: "12px",
                }}
              >
                New Password
              </label>
              <div style={{ position: "relative" }}>
                <Lock
                  size={20}
                  style={{
                    position: "absolute",
                    left: "16px",
                    top: "50%",
                    transform: "translateY(-50%)",
                    color: "#64748b",
                  }}
                />
                <input
                  type="password"
                  id="set-password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  style={{
                    width: "100%",
                    paddingLeft: "52px",
                    paddingRight: "16px",
                    paddingTop: "16px",
                    paddingBottom: "16px",
                    fontSize: "15px",
                    background: "var(--auth-input-bg)",
                    border: "1px solid var(--auth-input-border)",
                    borderRadius: "16px",
                    color: "var(--auth-text)",
                    outline: "none",
                    transition: "border-color 0.3s, box-shadow 0.3s",
                    boxSizing: "border-box",
                  }}
                  onFocus={(e) => {
                    e.target.style.borderColor = "rgba(59,130,246,0.5)";
                    e.target.style.boxShadow = "0 0 0 3px rgba(59,130,246,0.15)";
                  }}
                  onBlur={(e) => {
                    e.target.style.borderColor = "var(--auth-input-border)";
                    e.target.style.boxShadow = "none";
                  }}
                />
              </div>
            </div>

            {/* Confirm Password Field */}
            <div style={{ marginBottom: "28px" }}>
              <label
                htmlFor="set-password-confirm"
                style={{
                  display: "block",
                  fontSize: "14px",
                  fontWeight: 600,
                  color: "var(--auth-label)",
                  marginBottom: "12px",
                }}
              >
                Confirm Password
              </label>
              <div style={{ position: "relative" }}>
                <Lock
                  size={20}
                  style={{
                    position: "absolute",
                    left: "16px",
                    top: "50%",
                    transform: "translateY(-50%)",
                    color: "#64748b",
                  }}
                />
                <input
                  type="password"
                  id="set-password-confirm"
                  placeholder="••••••••"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  required
                  style={{
                    width: "100%",
                    paddingLeft: "52px",
                    paddingRight: "16px",
                    paddingTop: "16px",
                    paddingBottom: "16px",
                    fontSize: "15px",
                    background: "var(--auth-input-bg)",
                    border: "1px solid var(--auth-input-border)",
                    borderRadius: "16px",
                    color: "var(--auth-text)",
                    outline: "none",
                    transition: "border-color 0.3s, box-shadow 0.3s",
                    boxSizing: "border-box",
                  }}
                  onFocus={(e) => {
                    e.target.style.borderColor = "rgba(59,130,246,0.5)";
                    e.target.style.boxShadow = "0 0 0 3px rgba(59,130,246,0.15)";
                  }}
                  onBlur={(e) => {
                    e.target.style.borderColor = "var(--auth-input-border)";
                    e.target.style.boxShadow = "none";
                  }}
                />
              </div>
            </div>

            {/* Error */}
            {error && (
              <div
                style={{
                  background: "rgba(239, 68, 68, 0.12)",
                  border: "1px solid rgba(239, 68, 68, 0.3)",
                  borderRadius: "16px",
                  padding: "16px",
                  display: "flex",
                  alignItems: "center",
                  gap: "12px",
                  marginBottom: "28px",
                }}
              >
                <AlertCircle size={18} style={{ color: "var(--auth-error)", flexShrink: 0 }} />
                <span style={{ color: "var(--auth-error)", fontSize: "14px", fontWeight: 500 }}>{error}</span>
              </div>
            )}

            {/* Submit Button */}
            <button
              type="submit"
              id="set-password-submit"
              disabled={mutation.isPending}
              style={{
                width: "100%",
                background: "linear-gradient(90deg, #1f6feb 0%, #2f6fed 100%)",
                color: "#fff",
                fontWeight: 600,
                fontSize: "16px",
                padding: "18px 24px",
                borderRadius: "16px",
                border: "none",
                cursor: mutation.isPending ? "not-allowed" : "pointer",
                opacity: mutation.isPending ? 0.5 : 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "10px",
                boxShadow: "0 8px 24px rgba(59,130,246,0.3)",
                transition: "all 0.3s",
                marginBottom: "24px",
              }}
            >
              {mutation.isPending ? (
                <>
                  <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
                  <span>Updating Password...</span>
                </>
              ) : (
                <span>Update Password</span>
              )}
            </button>

            {/* Back to Login */}
            <div style={{ textAlign: "center" }}>
              <Link
                to="/login"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "8px",
                  fontSize: "14px",
                  color: "#64748b",
                  textDecoration: "none",
                  transition: "color 0.2s",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.color = "var(--auth-text)")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text-muted)")}
              >
                <ArrowLeft size={15} /> Back to Login
              </Link>
            </div>
          </form>
        </div>

        {/* Footer */}
        <div style={{ textAlign: "center", marginTop: "32px" }}>
          <p style={{ color: "var(--text-muted)", fontSize: "13px" }}>
            &copy; 2026 BreakProtection Security Standard
          </p>
        </div>
      </div>
    </div>
  );
}
