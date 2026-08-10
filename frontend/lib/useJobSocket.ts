import { useEffect, useRef, useState } from "react";
import { getToken, JobStatus } from "./api";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

function wsUrl(jobId: string, token: string): string {
  const u = new URL(API_URL);
  const proto = u.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${u.host}/ws/jobs/${jobId}?token=${encodeURIComponent(token)}`;
}

/**
 * Additive resilience, not a replacement: callers keep their existing
 * poll() + setInterval exactly as before. This hook independently opens a
 * WebSocket and, on success, calls onMessage with the same JobStatus shape
 * api.getJob() returns. The returned `connected` flag lets the caller slow
 * its own polling interval down (not stop it) while the socket is up, and
 * it snaps back to the original fast interval automatically the moment
 * `connected` goes false (first-connect failure, or a drop).
 */
export function useJobSocket(jobId: string | undefined, onMessage: (data: JobStatus) => void): boolean {
  const [connected, setConnected] = useState(false);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    if (!jobId) return;
    const token = getToken();
    if (!token) return;

    let cancelled = false;
    let socket: WebSocket;
    try {
      socket = new WebSocket(wsUrl(jobId, token));
    } catch {
      return; // existing polling is unaffected
    }

    socket.onopen = () => !cancelled && setConnected(true);
    socket.onmessage = (e) => {
      if (cancelled) return;
      try {
        onMessageRef.current(JSON.parse(e.data));
      } catch {
        // malformed frame — next message or the polling fallback catches up
      }
    };
    socket.onerror = () => !cancelled && setConnected(false);
    socket.onclose = () => !cancelled && setConnected(false);

    return () => {
      cancelled = true;
      socket.close();
    };
  }, [jobId]);

  return connected;
}
