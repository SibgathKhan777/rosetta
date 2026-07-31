"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }
    setLoading(true);
    try {
      const res = await api.resetPassword(token, password);
      setMessage(res.message);
      setTimeout(() => router.push("/login"), 1800);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reset that password.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "2rem 1.25rem",
        background:
          "radial-gradient(ellipse at 50% 0%, var(--stone-raised) 0%, var(--stone) 62%)",
      }}
    >
      <div style={{ marginBottom: "2.25rem", textAlign: "center" }}>
        <div className="wordmark" style={{ fontSize: "1.7rem", color: "var(--ink)" }}>
          Rosetta
        </div>
        <p style={{ color: "var(--ink-faint)", fontSize: "0.85rem", marginTop: "0.4rem" }}>
          Every video, decoded.
        </p>
      </div>

      <div className="panel" style={{ width: "100%", maxWidth: 380, padding: "2rem 1.75rem" }}>
        <h1 style={{ fontFamily: "var(--serif)", fontSize: "1.35rem", fontWeight: 500, marginBottom: "1.5rem" }}>
          Set a new password
        </h1>

        {!token ? (
          <p style={{ color: "var(--danger)", fontSize: "0.9rem" }}>
            This reset link is missing its token. Request a new one from the{" "}
            <Link href="/forgot-password" style={{ color: "var(--gold)", textDecoration: "underline" }}>
              forgot password
            </Link>{" "}
            page.
          </p>
        ) : message ? (
          <p style={{ fontSize: "0.9rem", color: "var(--patina)" }}>{message} Redirecting to login…</p>
        ) : (
          <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: "0.9rem" }}>
            <input
              className="field"
              type="password"
              placeholder="New password (min. 8 characters)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              autoFocus
            />
            <input
              className="field"
              type="password"
              placeholder="Confirm new password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={8}
            />
            {error && <p style={{ color: "var(--danger)", fontSize: "0.87rem" }}>{error}</p>}
            <button className="btn-primary" type="submit" disabled={loading} style={{ marginTop: "0.3rem" }}>
              {loading ? "Updating…" : "Update password"}
            </button>
          </form>
        )}

        <p style={{ marginTop: "1.4rem", fontSize: "0.87rem", color: "var(--ink-dim)" }}>
          <Link href="/login" style={{ color: "var(--gold)", textDecoration: "underline" }}>
            ← Back to log in
          </Link>
        </p>
      </div>
    </main>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordForm />
    </Suspense>
  );
}
