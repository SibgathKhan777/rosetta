"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, setToken, ApiError } from "@/lib/api";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { access_token } = await api.signup(email, password);
      setToken(access_token);
      router.push("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create that account.");
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
          Create an account
        </h1>
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
          <input
            className="field"
            type="password"
            placeholder="Password (min. 8 characters)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
          />
          {error && (
            <p style={{ color: "var(--danger)", fontSize: "0.87rem" }}>{error}</p>
          )}
          <button className="btn-primary" type="submit" disabled={loading} style={{ marginTop: "0.3rem" }}>
            {loading ? "Creating account…" : "Sign up"}
          </button>
        </form>
        <p style={{ marginTop: "1.4rem", fontSize: "0.87rem", color: "var(--ink-dim)" }}>
          Already have an account?{" "}
          <Link href="/login" style={{ color: "var(--gold)", textDecoration: "underline" }}>
            Log in
          </Link>
        </p>
      </div>
    </main>
  );
}
