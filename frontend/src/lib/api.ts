import type {
  AgentStats, AuthUser, CorpusStatus, DemoCredentialsResponse, EvaluationResponse, ExaminerDecisionValue, Health,
  LoginResponse, PetitionPayload, RunList, RunView, Stats, SystemOverview, Trace, ValidationFieldError,
} from "./types";

// All calls go to /api/* (Vite proxy in dev, nginx in Docker) which maps to the FastAPI backend.
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

const TOKEN_KEY = "academic_triage_auth_token";

export function getStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setStoredToken(token: string | null): void {
  try {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    // localStorage unavailable (e.g. incognito restriction)
  }
}

export class ApiError extends Error {
  status: number;
  fieldErrors: ValidationFieldError[];
  retryAfter?: number;
  constructor(message: string, status: number, fieldErrors: ValidationFieldError[] = [], retryAfter?: number) {
    super(message);
    this.status = status;
    this.fieldErrors = fieldErrors;
    this.retryAfter = retryAfter;
  }
}

async function parseError(r: Response): Promise<ApiError> {
  let body: unknown = null;
  try { body = await r.json(); } catch { /* not JSON */ }
  const b = body as { detail?: unknown; errors?: ValidationFieldError[]; retry_after_seconds?: number } | null;
  if (r.status === 422 && b?.errors) return new ApiError("The petition failed validation", 422, b.errors);
  let msg = `Request failed (HTTP ${r.status})`;
  if (typeof b?.detail === "string") msg = b.detail;
  else if (Array.isArray(b?.detail)) msg = (b!.detail as { msg?: string }[]).map((d) => d.msg).filter(Boolean).join("; ") || msg;
  return new ApiError(msg, r.status, [], b?.retry_after_seconds);
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  const token = getStoredToken();
  const headers = new Headers(init?.headers);
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  try {
    r = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError("The backend is unreachable. Check that the API service is running.", 0);
  }
  if (!r.ok) {
    if (r.status === 401 && token) {
      // Token invalid or expired
      setStoredToken(null);
    }
    throw await parseError(r);
  }
  return (await r.json()) as T;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  // --- Authentication ---
  login: (data: { user_id: string; password: string; role?: "student" | "examiner" }) =>
    req<LoginResponse>("/v1/auth/login", json("POST", data)),
  studentLogin: (data: { user_id: string; password: string }) =>
    req<LoginResponse>("/v1/auth/student/login", json("POST", data)),
  examinerLogin: (data: { user_id: string; password: string }) =>
    req<LoginResponse>("/v1/auth/examiner/login", json("POST", data)),
  logout: () => req<{ message: string; success: boolean }>("/v1/auth/logout", { method: "POST" }),
  me: () => req<AuthUser>("/v1/auth/me"),
  demoCredentials: () => req<DemoCredentialsResponse>("/v1/auth/demo-credentials"),

  // --- Core Petitions & Runs ---
  health: () => req<Health>("/readyz"),
  runs: (p: { limit?: number; offset?: number; status?: string; student_ref?: string; petition_type?: string; real_only?: boolean; awaiting_decision?: boolean } = {}) => {
    const q = new URLSearchParams();
    Object.entries(p).forEach(([k, v]) => v !== undefined && v !== "" && v !== false && q.set(k, String(v)));
    return req<RunList>(`/v1/runs?${q}`);
  },
  run: (id: string) => req<RunView>(`/v1/runs/${encodeURIComponent(id)}`),
  trace: (id: string) => req<Trace>(`/v1/runs/${encodeURIComponent(id)}/trace`),
  submit: (p: PetitionPayload) => req<{ run_id: string; status: string }>("/v1/petitions", json("POST", p)),
  uploadDocument: (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<{ document_id: number; filename: string; size: number; sha256: string; note: string }>(`/v1/runs/${encodeURIComponent(id)}/documents`, { method: "POST", body: fd });
  },
  documentUrl: (id: string, docId: number) => `${BASE}/v1/runs/${encodeURIComponent(id)}/documents/${docId}`,
  examinerDecision: (id: string, body: { decision: ExaminerDecisionValue; note: string; examiner_label?: string }) =>
    req<{ decision_id: number }>(`/v1/runs/${encodeURIComponent(id)}/examiner-decision`, json("POST", { ...body, examiner_label: body.examiner_label || "Examiner" })),
  feedback: (id: string, body: { rating: number; agrees_with_recommendation?: boolean; comment?: string }) =>
    req<{ stored: boolean }>(`/v1/runs/${encodeURIComponent(id)}/feedback`, json("POST", body)),
  stats: (realOnly: boolean) => req<Stats>(`/v1/stats?real_only=${realOnly}`),
  agentStats: (realOnly: boolean) => req<AgentStats>(`/v1/stats/agents?real_only=${realOnly}`),
  system: () => req<SystemOverview>("/v1/system"),
  corpus: () => req<CorpusStatus>("/v1/corpus"),
  evaluation: () => req<EvaluationResponse>("/v1/evaluation"),
};
