"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, getToken, clearToken, ApiError, JobListItem, Credits } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";

export default function HomePage() {
  const router = useRouter();
  const [authed, setAuthed] = useState(false);
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(true);
  const [credits, setCredits] = useState<Credits | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    setAuthed(true);
  }, [router]);

  async function refreshJobs() {
    try {
      const list = await api.listJobs();
      setJobs(list);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearToken();
        router.push("/login");
      }
    } finally {
      setLoadingJobs(false);
    }
  }

  useEffect(() => {
    if (!authed) return;
    refreshJobs();
    api.getCredits().then(setCredits).catch(() => {});
    const interval = setInterval(refreshJobs, 5000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authed]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { job_id } = await api.createJob(url);
      setUrl("");
      router.push(`/jobs/${job_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to submit job");
    } finally {
      setSubmitting(false);
      api.getCredits().then(setCredits).catch(() => {});
    }
  }

  function logout() {
    clearToken();
    router.push("/login");
  }

  if (!authed) return null;

  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: "2rem 1rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "2rem" }}>
        <h1>Video Extraction</h1>
        <div style={{ display: "flex", gap: "1rem", alignItems: "center" }}>
          {credits && (
            <span style={{ fontSize: "0.85rem", opacity: 0.8 }}>
              {credits.credits_remaining} credits
            </span>
          )}
          <button onClick={logout}>Log out</button>
        </div>
      </div>

      <form onSubmit={onSubmit} style={{ display: "flex", gap: "0.5rem", marginBottom: "2rem" }}>
        <input
          type="url"
          placeholder="Paste a video URL (YouTube, Instagram, TikTok, X...)"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          required
          style={{ flex: 1 }}
        />
        <button type="submit" disabled={submitting}>
          {submitting ? "Submitting..." : "Extract"}
        </button>
      </form>
      {error && <p style={{ color: "#e5484d", marginTop: "-1rem", marginBottom: "1rem" }}>{error}</p>}

      <h2 style={{ marginBottom: "1rem" }}>Job history</h2>
      {loadingJobs ? (
        <p>Loading...</p>
      ) : jobs.length === 0 ? (
        <p>No jobs yet — paste a link above to get started.</p>
      ) : (
        <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          {jobs.map((job) => (
            <li key={job.job_id}>
              <Link
                href={`/jobs/${job.job_id}`}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: "1rem",
                  padding: "0.75rem 1rem",
                  border: "1px solid #444",
                  borderRadius: 8,
                }}
              >
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {job.url}
                </span>
                <span style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexShrink: 0 }}>
                  {job.platform && <span style={{ fontSize: "0.8rem", opacity: 0.7 }}>{job.platform}</span>}
                  <StatusBadge status={job.status} />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
