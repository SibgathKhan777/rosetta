"use client";

import { useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.forgotPassword(email);
      setMessage(res.message);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't send that reset link.");
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
        <h1 style={{ fontFamily: "var(--serif)", fontSize: "1.35rem", fontWeight: 500, marginBottom: "0.6rem" }}>
          Reset your password
        </h1>
        <p style={{ fontSize: "0.87rem", color: "var(--ink-dim)", marginBottom: "1.4rem" }}>
          Enter your email and we&apos;ll send a link to reset it.
        </p>

        {message ? (
          <p style={{ fontSize: "0.9rem", color: "var(--patina)" }}>{message}</p>
        ) : (
          <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: "0.9rem" }}>
            <input
              className="field"
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
            {error && <p style={{ color: "var(--danger)", fontSize: "0.87rem" }}>{error}</p>}
            <button className="btn-primary" type="submit" disabled={loading} style={{ marginTop: "0.3rem" }}>
              {loading ? "Sending…" : "Send reset link"}
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
