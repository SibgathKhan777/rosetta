const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

export type JobProgress = {
  stage: string;
  percent_complete: number;
};

export type JobResult = {
  transcript: string | null;
  transcript_segments: { start: number; end: number; text: string }[] | null;
  ocr_events: { text: string; timestamp: number; confidence: number | null; source?: string }[] | null;
  metadata: Record<string, unknown> | null;
};

export type JobStatus = {
  job_id: string;
  url: string;
  platform: string | null;
  status: string;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  progress: JobProgress[];
  result: JobResult | null;
};

export type JobListItem = {
  job_id: string;
  url: string;
  platform: string | null;
  status: string;
  created_at: string;
  completed_at: string | null;
};

export type Credits = {
  credits_remaining: number;
  credits_used_total: number;
};

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

export function setToken(token: string) {
  localStorage.setItem("token", token);
}

export function clearToken() {
  localStorage.removeItem("token");
}

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // ignore
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  signup: (email: string, password: string) =>
    request<{ access_token: string }>("/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  login: (email: string, password: string) =>
    request<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  createJob: (url: string) =>
    request<{ job_id: string; status: string; platform: string }>("/jobs", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  listJobs: () => request<JobListItem[]>("/jobs"),
  getJob: (id: string) => request<JobStatus>(`/jobs/${id}`),
  getCredits: () => request<Credits>("/credits"),
};

export { ApiError };
