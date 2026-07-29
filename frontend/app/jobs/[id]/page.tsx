"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api, getToken, ApiError, JobStatus } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";

const TERMINAL_STATUSES = new Set(["done", "failed"]);

function formatTimestamp(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }

    let cancelled = false;
    let interval: ReturnType<typeof setInterval> | undefined;

    async function poll() {
      try {
        const data = await api.getJob(id);
        if (cancelled) return;
        setJob(data);
        if (TERMINAL_STATUSES.has(data.status) && interval) {
          clearInterval(interval);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        setError(err instanceof ApiError ? err.message : "Failed to load job");
      }
    }

    poll();
    interval = setInterval(poll, 2000);
    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, [id, router]);

  if (error) {
    return (
      <main style={{ maxWidth: 720, margin: "0 auto", padding: "2rem 1rem" }}>
        <p style={{ color: "#e5484d" }}>{error}</p>
      </main>
    );
  }

  if (!job) {
    return (
      <main style={{ maxWidth: 720, margin: "0 auto", padding: "2rem 1rem" }}>
        <p>Loading...</p>
      </main>
    );
  }

  const overallPercent =
    job.progress.length > 0
      ? job.progress.reduce((sum, p) => sum + p.percent_complete, 0) / job.progress.length
      : 0;
  const isTerminal = TERMINAL_STATUSES.has(job.status);

  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: "2rem 1rem" }}>
      <Link href="/" style={{ textDecoration: "underline" }}>
        &larr; Back
      </Link>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", margin: "1rem 0" }}>
        <h1 style={{ fontSize: "1.25rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {job.url}
        </h1>
        <StatusBadge status={job.status} />
      </div>

      {job.error_message && (
        <p style={{ color: job.status === "failed" ? "#e5484d" : "#f59e0b", marginBottom: "1rem" }}>
          {job.error_message}
        </p>
      )}

      {!isTerminal && (
        <div style={{ marginBottom: "2rem" }}>
          <div style={{ background: "#333", borderRadius: 999, height: 8, overflow: "hidden" }}>
            <div
              style={{
                width: `${overallPercent}%`,
                background: "#0ea5e9",
                height: "100%",
                transition: "width 0.4s ease",
              }}
            />
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem", marginTop: "0.5rem", fontSize: "0.85rem", opacity: 0.8 }}>
            {job.progress.map((p) => (
              <span key={p.stage}>
                {p.stage}: {Math.round(p.percent_complete)}%
              </span>
            ))}
          </div>
        </div>
      )}

      {job.result?.metadata && (
        <section style={{ marginBottom: "2rem" }}>
          <h2 style={{ marginBottom: "0.5rem" }}>Metadata</h2>
          <p><strong>{String(job.result.metadata.title ?? "")}</strong></p>
          <p style={{ opacity: 0.8 }}>by {String(job.result.metadata.uploader ?? "unknown")}</p>
          {typeof job.result.metadata.caption === "string" && job.result.metadata.caption && (
            <p style={{ whiteSpace: "pre-wrap", marginTop: "0.5rem" }}>{job.result.metadata.caption}</p>
          )}
        </section>
      )}

      {job.result?.transcript && (
        <section style={{ marginBottom: "2rem" }}>
          <h2 style={{ marginBottom: "0.5rem" }}>Transcript</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {(job.result.transcript_segments ?? []).map((seg, i) => (
              <p key={i}>
                <span style={{ opacity: 0.6, marginRight: "0.5rem" }}>{formatTimestamp(seg.start)}</span>
                {seg.text}
              </p>
            ))}
          </div>
        </section>
      )}

      {job.result?.ocr_events && job.result.ocr_events.length > 0 && (
        <section>
          <h2 style={{ marginBottom: "0.5rem" }}>On-screen text</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {job.result.ocr_events.map((event, i) => (
              <p key={i}>
                <span style={{ opacity: 0.6, marginRight: "0.5rem" }}>{formatTimestamp(event.timestamp)}</span>
                {event.text}
                {event.source === "vision_llm" && (
                  <span style={{ marginLeft: "0.5rem", fontSize: "0.75rem", opacity: 0.6 }}>(vision-LLM)</span>
                )}
              </p>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
