// Types mirror the FastAPI contracts (src/triage/contracts.py). Nothing here is mock data.
export type RunStatus = "queued" | "running" | "completed" | "escalated" | "failed";
export type Route = "grant-under-provision" | "refer-to-committee" | "reject";
export type PetitionType = "attendance" | "re-evaluation" | "re-registration" | "medical-leave" | "grade-grievance";
export type ExaminerDecisionValue = "accept-petition" | "reject-petition" | "request-more-information";

export interface PetitionPayload {
  student_ref: string;
  program: string;
  admission_batch: string;
  petition_type: PetitionType;
  course_code: string;
  semester: number;
  classes_held?: number;
  classes_attended?: number;
  attendance_percentage?: number;
  reason_category: "medical" | "personal" | "sports-cultural" | "other";
  medical_documentation: "none" | "certificate" | "hospital-record";
  period_start?: string;
  period_end?: string;
  petition_text: string;
}

export interface Citation {
  evidence_id: string;
  chunk_id: string;
  document: string;
  chapter: string;
  clause_id: string;
  page: number;
  quote: string;
  verified: boolean;
}

export interface Escalation { required: boolean; reason: string | null; detail: string }
export interface OpenQuestion { id: string; topic: string; text: string }

export interface RunResult {
  mode: "agents" | "placeholder";
  route: Route;
  position: string;
  basis: string;
  citations: Citation[];
  escalation: Escalation;
  evidence_reviewed?: { evidence_id: string; chunk_id: string; clause_id: string; page: number }[];
  triage?: { confidence: number; summary: string; flags: string[]; classified_type: string; declared_type: string; attendance_percentage: number | null; medical_grounds_claimed: boolean; documentation: string; supported: boolean } | null;
  prompt_versions?: Record<string, string>;
  agent_stats?: { steps: Record<string, number>; tool_calls: number; verify_attempts: number; research_stop_reason: string | null };
  usage?: Record<string, { prompt_tokens: number; completion_tokens: number; calls: number }>;
  llm_models?: string[];
  cost?: { llm_calls: number; prompt_tokens: number; completion_tokens: number; estimated_cost_usd: number | null; token_source: string };
  open_questions?: OpenQuestion[];
  human_review_checklist?: string[];
  human_review_required?: boolean;
  disclaimer: string;
  message: string;
}

export interface RunEvent { ts: string; event: string; detail: Record<string, unknown> }
export interface ExaminerDecisionRecord {
  id: number; ts: string; examiner_label: string; decision: ExaminerDecisionValue; note: string;
  ai_snapshot: { status?: string; route?: string | null; position?: string | null; escalation_reason?: string | null; citations?: string[]; llm_models?: string[] | null };
}
export interface DocumentRecord { id: number; ts: string; filename: string; content_type: string; size: number; sha256: string }

export interface RunView {
  run_id: string;
  status: RunStatus;
  created_at: string;
  updated_at: string;
  petition_type: PetitionType | null;
  student_ref: string | null;
  mode: string;
  result: RunResult | null;
  error: string | null;
  events: RunEvent[];
  petition: PetitionPayload | null;
  examiner_decisions: ExaminerDecisionRecord[];
  documents: DocumentRecord[];
}

export interface RunSummary {
  run_id: string; status: RunStatus; created_at: string; updated_at?: string | null;
  petition_type: PetitionType | null; student_ref: string | null; course_code?: string | null;
  attendance_percentage?: number | null; route?: Route | null; escalation_reason?: string | null;
  examiner_decision?: ExaminerDecisionValue | null; llm_models: string[];
}
export interface RunList { counts: Record<string, number>; runs: RunSummary[]; matched: number }

export interface Health { status: string; checks: Record<string, string> }
export interface CorpusStatus {
  ready: boolean; sources_present: string[]; index_exists: boolean; chroma_reachable: boolean; documents_indexed: number;
  chunks_indexed: number; embedding_tag: string | null; last_ingest_at: string | null; warnings: string[]; errors: string[];
  verified_passages: Record<string, boolean>; difficult_case: { status: string; note: string }; message: string;
}
export interface Stats {
  runs_considered: number; real_only: boolean; by_status: Record<string, number>; by_type: Record<string, number>;
  by_day: Record<string, { total: number; escalated: number }>; by_model: Record<string, number>;
  escalation_reasons: Record<string, number>; latency_seconds: { p50: number | null; p95: number | null; n: number };
  tokens: { prompt: number; completion: number; runs_with_estimated_tokens: number };
  cost: { total_usd: number | null; usd_per_100_runs: number | null; runs_with_known_cost: number; runs_with_unknown_cost: number };
  feedback: { count: number; mean_rating: number | null; satisfaction_rate: number | null; agreement_rate: number | null };
}
export interface AgentStats { runs_considered: number; agents: Record<string, { executions: number; failures: number; mean_seconds: number | null; p95_seconds: number | null }> }
export interface SystemOverview {
  llm: { configured: boolean; model: string | null; fallback_configured: boolean; breaker?: string };
  limits: { max_run_seconds: number; llm_timeout_seconds: number; rate_limit_requests: number; rate_limit_window_seconds: number; cache_enabled: boolean };
  queue: { name?: string; queued?: number; started?: number; failed_jobs?: number; workers?: number; error?: string };
  retrieval: { chroma_reachable: boolean };
}
export interface EvalMetric { value: number | null; n: number }
export interface EvalReport {
  file: string;
  meta: { mode: string; model: string; scenario_count: number; generated_at: string; interpretation: string; research_prompt_version: string };
  metrics: Record<string, EvalMetric>;
  by_category?: Record<string, { n: number; task_success: number; escalation_accuracy: number }>;
}
export interface EvaluationResponse { reports: EvalReport[]; experiment: unknown }
export interface Trace {
  total_seconds: number; event_count: number; retry_count: number; correlation_id?: string;
  agents: Record<string, { runs: number; failures: number; seconds: number; llm_calls: number; tool_calls: number }>;
  llm_calls: { at_s: number; agent: string; ok: boolean; provider?: string; latency_s?: number | null; prompt_tokens?: number | null; completion_tokens?: number | null; error?: string | null }[];
  retrieval_history: { at_s: number; tool: string; args: Record<string, unknown>; ok: boolean; error?: string | null; results: { clause_id: string; page: number; score: number }[] }[];
  retries_and_fallbacks: { at_s: number; event: string; provider?: string; kind?: string }[];
}
export interface ValidationFieldError { field: string; rule: string; message: string }

export type UserRole = "student" | "examiner";

export interface AuthUser {
  user_id: string;
  role: UserRole;
  name: string;
  email?: string;
  branch?: string;
  semester?: number;
  section?: string;
  usn?: string;
  created_at?: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
}

export interface DemoCredentialItem {
  id: string;
  password: string;
  name: string;
  branch?: string;
  semester?: number;
  section?: string;
  usn?: string;
  title?: string;
}

export interface DemoCredentialsResponse {
  enabled: boolean;
  student: DemoCredentialItem;
  examiner: DemoCredentialItem;
  students?: DemoCredentialItem[];
  examiners?: DemoCredentialItem[];
}

