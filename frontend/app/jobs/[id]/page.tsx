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
        setError(err instanceof ApiError ? err.message : "Couldn't load this decode.");
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
      <main style={{ maxWidth: 720, margin: "0 auto", padding: "2rem 1.25rem" }}>
        <p style={{ color: "var(--danger)" }}>{error}</p>
      </main>
    );
  }

  if (!job) {
    return (
      <main style={{ maxWidth: 720, margin: "0 auto", padding: "2rem 1.25rem" }}>
        <p style={{ color: "var(--ink-dim)" }}>Loading…</p>
      </main>
    );
  }

  const overallPercent =
    job.progress.length > 0
      ? job.progress.reduce((sum, p) => sum + p.percent_complete, 0) / job.progress.length
      : 0;
  const isTerminal = TERMINAL_STATUSES.has(job.status);

  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: "2.5rem 1.25rem 4rem" }}>
      <Link href="/" style={{ color: "var(--gold)", fontSize: "0.9rem" }}>
        ← Back to Rosetta
      </Link>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", margin: "1.25rem 0 1.75rem", gap: "1rem" }}>
        <h1
          style={{
            fontFamily: "var(--serif)",
            fontWeight: 500,
            fontSize: "1.2rem",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {job.url}
        </h1>
        <StatusBadge status={job.status} />
      </div>

      {job.error_message && (
        <p
          style={{
            color: job.status === "failed" ? "var(--danger)" : "var(--gold)",
            marginBottom: "1.5rem",
            fontSize: "0.9rem",
          }}
        >
          {job.error_message}
        </p>
      )}

      {!isTerminal && (
        <div className="panel" style={{ padding: "1.1rem 1.25rem", marginBottom: "2.5rem" }}>
          <div style={{ background: "var(--stone-sunken)", borderRadius: 999, height: 8, overflow: "hidden" }}>
            <div
              style={{
                width: `${overallPercent}%`,
                background: "var(--gold)",
                height: "100%",
                transition: "width 0.4s ease",
              }}
            />
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem", marginTop: "0.7rem", fontSize: "0.82rem", color: "var(--ink-dim)" }}>
            {job.progress.map((p) => (
              <span key={p.stage} style={{ textTransform: "capitalize" }}>
                {p.stage}: {Math.round(p.percent_complete)}%
              </span>
            ))}
          </div>
        </div>
      )}

      {job.result?.metadata && (
        <section style={{ marginBottom: "2.5rem" }}>
          <SectionHeading>Metadata</SectionHeading>
          <p style={{ fontFamily: "var(--serif)", fontSize: "1.05rem" }}>
            {String(job.result.metadata.title ?? "")}
          </p>
          <p style={{ color: "var(--ink-dim)", fontSize: "0.9rem" }}>
            by {String(job.result.metadata.uploader ?? "unknown")}
          </p>
          {typeof job.result.metadata.caption === "string" && job.result.metadata.caption && (
            <p style={{ whiteSpace: "pre-wrap", marginTop: "0.6rem", fontSize: "0.9rem", color: "var(--ink-dim)" }}>
              {job.result.metadata.caption}
            </p>
          )}
        </section>
      )}

      {job.parts ? (
        job.parts.map((part) => (
          <section key={part.part_index} style={{ marginBottom: "2.5rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.7rem" }}>
              <SectionHeading>
                Part {part.part_index + 1} · {formatTimestamp(part.start_seconds)}–{formatTimestamp(part.end_seconds)}
              </SectionHeading>
              <StatusBadge status={part.status} />
            </div>

            {part.error_message && (
              <p
                style={{
                  color: part.status === "failed" ? "var(--danger)" : "var(--gold)",
                  marginBottom: "0.8rem",
                  fontSize: "0.85rem",
                }}
              >
                {part.error_message}
              </p>
            )}

            {part.status === "processing" && !part.transcript && !part.ocr_events && (
              <p style={{ color: "var(--ink-dim)", fontSize: "0.9rem" }}>Still decoding this part…</p>
            )}

            {part.transcript_segments && part.transcript_segments.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem", marginBottom: "1rem" }}>
                {part.transcript_segments.map((seg, i) => (
                  <p key={i} style={{ fontSize: "0.92rem" }}>
                    <span className="mono" style={{ color: "var(--ink-faint)", marginRight: "0.6rem", fontSize: "0.8rem" }}>
                      {formatTimestamp(seg.start)}
                    </span>
                    {seg.text}
                  </p>
                ))}
              </div>
            )}

            {part.ocr_events && part.ocr_events.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem", marginBottom: "1rem" }}>
                {part.ocr_events.map((event, i) => (
                  <p key={i} style={{ fontSize: "0.92rem" }}>
                    <span className="mono" style={{ color: "var(--ink-faint)", marginRight: "0.6rem", fontSize: "0.8rem" }}>
                      {formatTimestamp(event.timestamp)}
                    </span>
                    {event.text}
                    {event.source === "vision_llm" && (
                      <span style={{ marginLeft: "0.5rem", fontSize: "0.72rem", color: "var(--patina)" }}>(vision-LLM)</span>
                    )}
                  </p>
                ))}
              </div>
            )}

            {part.explanation && (
              <p style={{ whiteSpace: "pre-wrap", fontSize: "0.95rem", lineHeight: 1.7 }}>{part.explanation}</p>
            )}
          </section>
        ))
      ) : (
        <>
          {job.result?.transcript && (
            <section style={{ marginBottom: "2.5rem" }}>
              <SectionHeading>Transcript</SectionHeading>
              <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
                {(job.result.transcript_segments ?? []).map((seg, i) => (
                  <p key={i} style={{ fontSize: "0.92rem" }}>
                    <span className="mono" style={{ color: "var(--ink-faint)", marginRight: "0.6rem", fontSize: "0.8rem" }}>
                      {formatTimestamp(seg.start)}
                    </span>
                    {seg.text}
                  </p>
                ))}
              </div>
            </section>
          )}

          {job.result?.ocr_events && job.result.ocr_events.length > 0 && (
            <section style={{ marginBottom: "2.5rem" }}>
              <SectionHeading>On-screen text</SectionHeading>
              <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
                {job.result.ocr_events.map((event, i) => (
                  <p key={i} style={{ fontSize: "0.92rem" }}>
                    <span className="mono" style={{ color: "var(--ink-faint)", marginRight: "0.6rem", fontSize: "0.8rem" }}>
                      {formatTimestamp(event.timestamp)}
                    </span>
                    {event.text}
                    {event.source === "vision_llm" && (
                      <span style={{ marginLeft: "0.5rem", fontSize: "0.72rem", color: "var(--patina)" }}>(vision-LLM)</span>
                    )}
                  </p>
                ))}
              </div>
            </section>
          )}

          {job.result?.explanation && (
            <section>
              <SectionHeading>Explained for you</SectionHeading>
              <p style={{ whiteSpace: "pre-wrap", fontSize: "0.95rem", lineHeight: 1.7 }}>{job.result.explanation}</p>
            </section>
          )}
        </>
      )}
    </main>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2
      style={{
        fontFamily: "var(--serif)",
        fontWeight: 500,
        fontSize: "1.1rem",
        marginBottom: "0.7rem",
        paddingBottom: "0.35rem",
        borderBottom: "1px solid var(--rule)",
      }}
    >
      {children}
    </h2>
  );
}
