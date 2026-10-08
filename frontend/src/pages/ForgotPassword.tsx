import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import {
  Mail, ArrowLeft, CheckCircle2, Loader2, AlertCircle, KeyRound, Copy, ExternalLink,
} from "lucide-react";

interface ForgotResponse {
  message: string;
  reset_url?: string;
  token?: string;
}

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [resetResult, setResetResult] = useState<ForgotResponse | null>(null);
  const [copied, setCopied] = useState(false);

  const mutation = useMutation({
    mutationFn: (data: { email: string }) =>
      api.post<ForgotResponse>("/auth/forgot-password", data),
    onSuccess: (data) => setResetResult(data),
  });

  const copyLink = async () => {
    if (resetResult?.reset_url) {
      await navigator.clipboard.writeText(window.location.origin + resetResult.reset_url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
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
      <div style={{ position: "fixed", inset: 0, overflow: "hidden", pointerEvents: "none", zIndex: 0 }}>
        <div style={{ position: "absolute", top: "-20%", left: "-20%", width: "60%", height: "60%", background: "radial-gradient(circle, rgba(59,130,246,0.08) 0%, transparent 70%)", borderRadius: "50%" }} />
        <div style={{ position: "absolute", bottom: "-20%", right: "-20%", width: "60%", height: "60%", background: "radial-gradient(circle, rgba(168,85,247,0.08) 0%, transparent 70%)", borderRadius: "50%" }} />
      </div>

      <div style={{ position: "relative", width: "100%", maxWidth: "480px", margin: "0 auto", zIndex: 10 }}>
        <div style={{ textAlign: "center", marginBottom: "40px" }}>
          <div style={{ display: "inline-block", position: "relative", marginBottom: "20px" }}>
            <div
              style={{
                position: "absolute",
                inset: "-4px",
                background: "linear-gradient(135deg, #3b82f6, #8b5cf6)",
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
            Reset Password
          </h1>
          <p style={{ color: "var(--auth-muted)", fontSize: "14px" }}>
            Enter your email to get a password reset link
          </p>
        </div>

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
          {resetResult ? (
            <div style={{ textAlign: "center", padding: "16px 0" }}>
              <div
                style={{
                  width: "64px",
                  height: "64px",
                  borderRadius: "50%",
                  background: "rgba(16, 185, 129, 0.1)",
                  border: "1px solid rgba(16, 185, 129, 0.2)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  margin: "0 auto 20px",
                  color: "var(--auth-success)",
                }}
              >
                <CheckCircle2 size={32} />
              </div>
              <h3 style={{ fontSize: "20px", fontWeight: 600, color: "var(--auth-text)", marginBottom: "12px" }}>
                Reset Link Generated
              </h3>
              <p style={{ fontSize: "14px", color: "var(--auth-muted)", lineHeight: 1.6, marginBottom: "24px" }}>
                Use the link below to set a new password for{" "}
                <span style={{ color: "var(--auth-text)", fontWeight: 500 }}>{email}</span>.
              </p>

              {resetResult.reset_url && (
                <div style={{ marginBottom: "24px" }}>
                  <div
                    style={{
                      background: "var(--auth-input-bg)",
                      border: "1px solid var(--auth-input-border)",
                      borderRadius: "12px",
                      padding: "14px 16px",
                      display: "flex",
                      alignItems: "center",
                      gap: "12px",
                      marginBottom: "16px",
                    }}
                  >
                    <KeyRound size={16} style={{ color: "var(--auth-link)", flexShrink: 0 }} />
                    <span
                      style={{
                        fontSize: "13px",
                        color: "var(--auth-code)",
                        fontFamily: "monospace",
                        wordBreak: "break-all",
                        textAlign: "left",
                        flex: 1,
                      }}
                    >
                      {window.location.origin}{resetResult.reset_url}
                    </span>
                  </div>

                  <div style={{ display: "flex", gap: "12px", justifyContent: "center" }}>
                    <button
                      onClick={copyLink}
                      style={{
                        background: "rgba(59,130,246,0.15)",
                        border: "1px solid rgba(59,130,246,0.3)",
                        borderRadius: "12px",
                        padding: "10px 20px",
                        color: "var(--auth-link)",
                        fontWeight: 600,
                        fontSize: "14px",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                        transition: "all 0.2s",
                      }}
                    >
                      <Copy size={16} />
                      {copied ? "Copied!" : "Copy Link"}
                    </button>
                    <Link
                      to={resetResult.reset_url}
                      style={{
                        background: "linear-gradient(90deg, #3b82f6 0%, #8b5cf6 100%)",
                        border: "none",
                        borderRadius: "12px",
                        padding: "10px 20px",
                        color: "#fff",
                        fontWeight: 600,
                        fontSize: "14px",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                        textDecoration: "none",
                        transition: "all 0.2s",
                        boxShadow: "0 4px 16px rgba(59,130,246,0.3)",
                      }}
                    >
                      <ExternalLink size={16} />
                      Reset Now
                    </Link>
                  </div>
                </div>
              )}

              <Link
                to="/login"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "8px",
                  fontSize: "14px",
                  fontWeight: 600,
                  color: "var(--auth-link)",
                  textDecoration: "none",
                }}
              >
                <ArrowLeft size={16} /> Back to Login
              </Link>
            </div>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                mutation.mutate({ email });
              }}
            >
              <div style={{ marginBottom: "28px" }}>
                <label
                  htmlFor="forgot-email"
                  style={{
                    display: "block",
                    fontSize: "14px",
                    fontWeight: 600,
                    color: "var(--auth-label)",
                    marginBottom: "12px",
                  }}
                >
                  Registered Email
                </label>
                <div style={{ position: "relative" }}>
                  <Mail
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
                    type="email"
                    id="forgot-email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="user@breakprotection.com"
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

              {mutation.isError && (
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
                  <span style={{ color: "var(--auth-error)", fontSize: "14px", fontWeight: 500 }}>
                    {(mutation.error as any)?.message || "Failed to request password reset"}
                  </span>
                </div>
              )}

              <button
                type="submit"
                id="forgot-submit"
                disabled={mutation.isPending}
                style={{
                  width: "100%",
                  background: "linear-gradient(90deg, #3b82f6 0%, #8b5cf6 100%)",
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
                    <span>Generating Reset Link...</span>
                  </>
                ) : (
                  <span>Generate Reset Link</span>
                )}
              </button>

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
                  onMouseLeave={(e) => (e.currentTarget.style.color = "#64748b")}
                >
                  <ArrowLeft size={15} /> Back to Login
                </Link>
              </div>
            </form>
          )}
        </div>

        <div style={{ textAlign: "center", marginTop: "32px" }}>
          <p style={{ color: "#64748b", fontSize: "13px" }}>
            &copy; 2026 BreakProtection Security Standard
          </p>
        </div>
      </div>
    </div>
  );
}
