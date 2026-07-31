"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, getToken, clearToken, ApiError, JobListItem, JobStatus, Credits } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";

const TERMINAL_STATUSES = new Set(["done", "failed"]);
const STAGE_LABEL: Record<string, string> = {
  download: "Reading the source",
  split: "Splitting into chunks",
  transcription: "Listening",
  ocr: "Reading on-screen text",
  stitching: "Stitching the decode",
  parts: "Processing in parts",
};

function truncate(text: string | null | undefined, n: number): string {
  if (!text) return "";
  const clean = text.trim().replace(/\s+/g, " ");
  return clean.length > n ? clean.slice(0, n).trimEnd() + "…" : clean;
}

function currentStageLabel(job: JobStatus): string {
  const active = job.progress.find((p) => p.percent_complete < 100);
  const stage = active?.stage || job.progress[job.progress.length - 1]?.stage;
  return (stage && STAGE_LABEL[stage]) || "Decoding";
}

export default function HomePage() {
  const router = useRouter();
  const [authed, setAuthed] = useState(false);
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [details, setDetails] = useState<Record<string, JobStatus>>({});
  const [credits, setCredits] = useState<Credits | null>(null);
  const threadEndRef = useRef<HTMLDivElement>(null);

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

  // Poll live detail (stage progress + result) for any job that isn't
  // finished yet, and fetch once for finished jobs missing a cached detail
  // (so the result-preview card has something to render).
  useEffect(() => {
    if (!authed || jobs.length === 0) return;
    let cancelled = false;

    async function fetchOne(jobId: string) {
      try {
        const data = await api.getJob(jobId);
        if (!cancelled) setDetails((prev) => ({ ...prev, [jobId]: data }));
      } catch {
        // best-effort — a missed poll just tries again next tick
      }
    }

    function tick() {
      for (const j of jobs) {
        const cached = details[j.job_id];
        if (!cached || !TERMINAL_STATUSES.has(cached.status)) {
          fetchOne(j.job_id);
        }
      }
    }

    tick();
    const interval = setInterval(tick, 2000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authed, jobs]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [jobs.length]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api.createJob(url);
      setUrl("");
      await refreshJobs();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't start that decode.");
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
    <div style={{ flex: 1, display: "flex", flexDirection: "column", height: "100vh" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "0.9rem 1.5rem",
          borderBottom: "1px solid var(--rule)",
          background: "var(--stone-raised)",
        }}
      >
        <span className="wordmark" style={{ fontSize: "1.1rem" }}>Rosetta</span>
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
          {credits && (
            <span className="pill" style={{ color: "var(--ink-dim)" }}>
              {credits.credits_remaining} credits
            </span>
          )}
          <button className="btn" onClick={logout}>Log out</button>
        </div>
      </header>

      <main
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "2rem 1.25rem 1rem",
        }}
      >
        <div style={{ maxWidth: 640, margin: "0 auto", display: "flex", flexDirection: "column", gap: "1.5rem" }}>
          {jobs.length === 0 ? (
            <div style={{ textAlign: "center", padding: "3rem 1rem", color: "var(--ink-dim)" }}>
              <p style={{ fontFamily: "var(--serif)", fontSize: "1.15rem", color: "var(--ink)", marginBottom: "0.5rem" }}>
                Paste a video below to begin.
              </p>
              <p style={{ fontSize: "0.9rem" }}>YouTube, Instagram, TikTok, X — the transcript, the on-screen text, and the teaching behind it.</p>
            </div>
          ) : (
            [...jobs].reverse().map((job) => (
              <JobTurn key={job.job_id} job={job} detail={details[job.job_id]} />
            ))
          )}
          <div ref={threadEndRef} />
        </div>
      </main>

      <form
        onSubmit={onSubmit}
        style={{
          display: "flex",
          gap: "0.6rem",
          padding: "1rem 1.25rem",
          borderTop: "1px solid var(--rule)",
          background: "var(--stone-raised)",
        }}
      >
        <div style={{ maxWidth: 640, margin: "0 auto", width: "100%", display: "flex", flexDirection: "column", gap: "0.4rem" }}>
          {error && <p style={{ color: "var(--danger)", fontSize: "0.85rem" }}>{error}</p>}
          <div style={{ display: "flex", gap: "0.6rem" }}>
            <input
              className="field"
              type="url"
              placeholder="Paste a video URL — YouTube, Instagram, TikTok, X…"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
              style={{ flex: 1 }}
            />
            <button className="btn-primary" type="submit" disabled={submitting}>
              {submitting ? "Sending…" : "Extract"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

function JobTurn({ job, detail }: { job: JobListItem; detail?: JobStatus }) {
  const status = detail?.status ?? job.status;
  const isTerminal = TERMINAL_STATUSES.has(status);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
      {/* user turn */}
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <div
          className="panel"
          style={{
            maxWidth: "85%",
            padding: "0.65rem 1rem",
            background: "var(--gold-soft)",
            borderColor: "var(--gold-line)",
          }}
        >
          <p style={{ fontSize: "0.9rem", wordBreak: "break-all" }}>{job.url}</p>
          {job.platform && (
            <p style={{ fontSize: "0.72rem", color: "var(--ink-faint)", marginTop: "0.2rem", textTransform: "capitalize" }}>
              {job.platform}
            </p>
          )}
        </div>
      </div>

      {/* assistant turn */}
      <div style={{ display: "flex", justifyContent: "flex-start" }}>
        <div className="panel" style={{ maxWidth: "90%", width: "100%", padding: "1.1rem 1.25rem" }}>
          {status === "failed" ? (
            <>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--danger)", fontWeight: 650 }}>Couldn&apos;t finish this decode</span>
                <StatusBadge status={status} />
              </div>
              <p style={{ fontSize: "0.85rem", color: "var(--ink-dim)" }}>
                {detail?.error_message || "Something went wrong partway through."}
              </p>
            </>
          ) : !isTerminal ? (
            <>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.7rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--ink-dim)" }}>
                  {detail ? currentStageLabel(detail) : "Starting up"}…
                </span>
                <StatusBadge status={status} />
              </div>
              <div className="shimmer" style={{ height: 10, borderRadius: 6, marginBottom: "0.4rem" }} />
              <div className="shimmer" style={{ height: 10, borderRadius: 6, width: "70%" }} />
            </>
          ) : (
            <ResultPreview job={job} detail={detail} />
          )}
        </div>
      </div>
    </div>
  );
}

function ResultPreview({ job, detail }: { job: JobListItem; detail?: JobStatus }) {
  const result = detail?.result;
  const title = (result?.metadata?.title as string) || job.url;
  const ocrCount = result?.ocr_events?.length ?? 0;

  return (
    <>
      <h3
        style={{
          fontFamily: "var(--serif)",
          fontSize: "1.05rem",
          fontWeight: 500,
          marginBottom: "0.5rem",
          borderBottom: "1px solid var(--gold-line)",
          display: "inline-block",
          paddingBottom: "0.15rem",
        }}
      >
        {title}
      </h3>
      {result?.transcript && (
        <p style={{ fontSize: "0.88rem", color: "var(--ink-dim)", marginBottom: "0.5rem" }}>
          {truncate(result.transcript, 160)}
        </p>
      )}
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.8rem" }}>
        {result?.transcript && <span className="pill">transcript</span>}
        {ocrCount > 0 && <span className="pill">{ocrCount} on-screen lines</span>}
        {result?.explanation && <span className="pill" style={{ color: "var(--patina)", borderColor: "var(--patina)" }}>explained</span>}
      </div>
      <Link href={`/jobs/${job.job_id}`} style={{ color: "var(--gold)", fontSize: "0.87rem", textDecoration: "underline" }}>
        Open full decode →
      </Link>
    </>
  );
}
