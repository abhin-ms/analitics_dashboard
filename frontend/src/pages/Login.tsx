import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuthStore } from "@/lib/authStore";
import { Mail, Lock, AlertCircle, ArrowRight, Loader2 } from "lucide-react";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const login = useAuthStore((s) => s.login);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      navigate("/dashboard");
    } catch (err: any) {
      setError(err.message || "Login failed. Please check your credentials.");
    } finally {
      setLoading(false);
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
            BP Analytics
          </h1>
          <p style={{ color: "var(--auth-muted)", fontSize: "14px" }}>
            Welcome back! Please sign in to your account
          </p>
        </div>

        {/* Login Form Card */}
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
            {/* Error Alert */}
            {error && (
              <div
                style={{
                  background: "rgba(239, 68, 68, 0.12)",
                  border: "1px solid rgba(239, 68, 68, 0.3)",
                  borderRadius: "16px",
                  padding: "16px",
                  display: "flex",
                  alignItems: "flex-start",
                  gap: "12px",
                  marginBottom: "32px",
                }}
              >
                <AlertCircle size={18} style={{ color: "var(--auth-error)", flexShrink: 0, marginTop: "2px" }} />
                <span style={{ color: "var(--auth-error)", fontSize: "14px", fontWeight: 500 }}>{error}</span>
              </div>
            )}

            {/* Email Field */}
            <div style={{ marginBottom: "28px" }}>
              <label
                htmlFor="login-email"
                style={{
                  display: "block",
                  fontSize: "14px",
                  fontWeight: 600,
                  color: "var(--auth-label)",
                  marginBottom: "12px",
                }}
              >
                Email Address
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
                  id="login-email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="Enter your email"
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

            {/* Password Field */}
            <div style={{ marginBottom: "16px" }}>
              <label
                htmlFor="login-password"
                style={{
                  display: "block",
                  fontSize: "14px",
                  fontWeight: 600,
                  color: "var(--auth-label)",
                  marginBottom: "12px",
                }}
              >
                Password
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
                  id="login-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter your password"
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

            {/* Forgot Password - below password field like reference */}
            <div style={{ textAlign: "right", marginBottom: "32px" }}>
              <Link
                to="/forgot-password"
                style={{
                  fontSize: "14px",
                  color: "var(--auth-link)",
                  textDecoration: "none",
                  fontWeight: 500,
                  transition: "color 0.2s",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.color = "var(--auth-link-hover)")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "var(--auth-link)")}
              >
                Forgot password?
              </Link>
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              id="login-submit"
              disabled={loading}
              style={{
                width: "100%",
                background: "linear-gradient(90deg, #3b82f6 0%, #8b5cf6 100%)",
                color: "#fff",
                fontWeight: 600,
                fontSize: "16px",
                padding: "18px 24px",
                borderRadius: "16px",
                border: "none",
                cursor: loading ? "not-allowed" : "pointer",
                opacity: loading ? 0.5 : 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "10px",
                boxShadow: "0 8px 24px rgba(59,130,246,0.3)",
                transition: "all 0.3s",
                marginBottom: "24px",
              }}
              onMouseEnter={(e) => {
                if (!loading) e.currentTarget.style.boxShadow = "0 12px 32px rgba(59,130,246,0.4)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.boxShadow = "0 8px 24px rgba(59,130,246,0.3)";
              }}
            >
              {loading ? (
                <>
                  <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
                  <span>Signing in...</span>
                </>
              ) : (
                <>
                  <span>Sign In</span>
                  <ArrowRight size={18} />
                </>
              )}
            </button>
          </form>
        </div>

        {/* Footer */}
        <div style={{ textAlign: "center", marginTop: "32px" }}>
          <p style={{ color: "#64748b", fontSize: "13px" }}>
            &copy; 2026 BreakProtection Security Standard
          </p>
        </div>
      </div>
    </div>
  );
}
