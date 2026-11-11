import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, CheckCircle2, Circle, CircleDashed, FileUp, Paperclip, ShieldAlert, XCircle } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Callout } from "@/components/ui/feedback";
import { api, ApiError } from "@/lib/api";
import type { Citation, DocumentRecord, ExaminerDecisionValue, Route, RunStatus, RunView } from "@/lib/types";
import { cn, formatBytes, formatDateTime, titleCase } from "@/lib/utils";

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0 space-y-1">
        {eyebrow && <p className="text-xs font-medium uppercase tracking-wider text-accent">{eyebrow}</p>}
        <h1 className="text-xl font-semibold tracking-tight md:text-2xl">{title}</h1>
        {description && <p className="max-w-2xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function StatCard({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: "warning" | "danger" | "success" }) {
  const color = tone === "warning" ? "text-warning" : tone === "danger" ? "text-danger" : tone === "success" ? "text-success" : "";
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className={cn("mt-1 text-2xl font-semibold tabular-nums tracking-tight", color)}>{value}</p>
        {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

const STATUS: Record<RunStatus, { label: string; tone: "neutral" | "info" | "success" | "warning" | "danger" }> = {
  queued: { label: "Queued", tone: "neutral" },
  running: { label: "AI analysing", tone: "info" },
  completed: { label: "AI recommendation ready", tone: "success" },
  escalated: { label: "Escalated to human", tone: "warning" },
  failed: { label: "Failed", tone: "danger" },
};
export function StatusBadge({ status }: { status: RunStatus }) {
  const s = STATUS[status];
  return <Badge tone={s.tone} dot>{s.label}</Badge>;
}

export const ROUTE_LABEL: Record<Route, string> = {
  "grant-under-provision": "Grant under a provision",
  "refer-to-committee": "Refer to the deciding authority",
  reject: "Reject, citing a clause",
};
export function RouteBadge({ route, noDetermination }: { route?: Route | null; noDetermination?: boolean }) {
  if (noDetermination) return <Badge tone="neutral">No determination</Badge>;
  if (!route) return <Badge tone="outline">—</Badge>;
  return <Badge tone={route === "reject" ? "danger" : route === "refer-to-committee" ? "warning" : "success"}>{ROUTE_LABEL[route]}</Badge>;
}

export const DECISION_LABEL: Record<ExaminerDecisionValue, string> = {
  "accept-petition": "Petition accepted",
  "reject-petition": "Petition rejected",
  "request-more-information": "More information requested",
};
export function DecisionBadge({ decision }: { decision?: ExaminerDecisionValue | null }) {
  if (!decision) return <Badge tone="outline">Awaiting human decision</Badge>;
  return <Badge tone={decision === "accept-petition" ? "success" : decision === "reject-petition" ? "danger" : "info"}>{DECISION_LABEL[decision]}</Badge>;
}

const ESC_TEXT: Record<string, string> = {
  committee_discretion: "The regulation reserves this decision to an authority (the Vice-Chancellor), so a human must decide.",
  corpus_insufficient: "The regulations available to the system do not settle this petition.",
  conflicting_provisions: "The retrieved provisions conflict with each other.",
  unsupported_petition_type: "This petition type is not covered by the verified regulations.",
  petition_inconsistent: "The petition's fields and text do not agree.",
  petition_ambiguous: "The petition is too vague to assess; clarification is needed.",
  verification_failed: "The model's citations could not be verified against the source text.",
  llm_unavailable: "The AI provider was unavailable, so no analysis was produced.",
  unsafe_input: "The text was flagged by automated safety checks and was not sent to the model.",
  output_blocked: "The model's output failed safety checks and was withheld.",
  retrieval_unavailable: "The regulation index could not be reached.",
  budget_exhausted: "The analysis hit its time or step limit.",
  invalid_agent_output: "The model returned output the system could not use.",
  agent_error: "An unexpected error stopped the analysis.",
};
export const escalationText = (reason?: string | null) => (reason ? ESC_TEXT[reason] ?? titleCase(reason) : "");

export function PipelineStepper({ run }: { run: RunView }) {
  const started = new Set(run.events.filter((e) => e.event === "agent_start").map((e) => String(e.detail.agent)));
  const ended = new Map(run.events.filter((e) => e.event === "agent_end").map((e) => [String(e.detail.agent), Boolean(e.detail.ok)]));
  const terminal = run.status === "completed" || run.status === "escalated" || run.status === "failed";
  const steps = [
    { label: "Submitted", state: run.status === "queued" ? "active" : "done" },
    ...(["triage", "research", "verifier"] as const).map((a) => ({
      label: titleCase(a),
      state: ended.has(a) ? (ended.get(a) ? "done" : "fail") : started.has(a) ? "active" : terminal ? "skip" : "todo",
    })),
    { label: "Human review", state: terminal ? "active" : "todo" },
  ];
  return (
    <ol className="flex flex-wrap items-center gap-x-2 gap-y-2 text-xs" aria-label="Processing pipeline">
      {steps.map((s, i) => (
        <li key={s.label} className="flex items-center gap-2">
          <span className={cn("flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium",
            s.state === "done" && "border-success/30 bg-success-soft text-success",
            s.state === "active" && "border-info/30 bg-info-soft text-info",
            s.state === "fail" && "border-danger/30 bg-danger-soft text-danger",
            (s.state === "todo" || s.state === "skip") && "text-muted-foreground")}>
            {s.state === "done" ? <CheckCircle2 className="size-3.5" /> : s.state === "fail" ? <XCircle className="size-3.5" /> : s.state === "active" ? <CircleDashed className="size-3.5 animate-spin [animation-duration:2.5s]" /> : <Circle className="size-3.5" />}
            {s.label}
            {s.state === "skip" && <span className="font-normal">(skipped)</span>}
          </span>
          {i < steps.length - 1 && <span className="h-px w-3 bg-border" aria-hidden />}
        </li>
      ))}
    </ol>
  );
}

export function CitationCard({ c }: { c: Citation }) {
  return (
    <figure className="rounded-lg border bg-card p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Badge tone="info" className="font-mono">{c.clause_id}</Badge>
        <span className="text-xs text-muted-foreground">page {c.page} · {c.document}</span>
        <Badge tone={c.verified ? "success" : "danger"} className="ml-auto"><BookOpenCheck className="size-3" />{c.verified ? "Quote found in source" : "Not verified"}</Badge>
      </div>
      <blockquote className="border-l-2 border-accent pl-3 text-sm leading-relaxed">“{c.quote}”</blockquote>
      <figcaption className="mt-2 text-xs text-muted-foreground">{c.chapter}</figcaption>
    </figure>
  );
}

export function RecommendationPanel({ run, audience }: { run: RunView; audience: "student" | "examiner" }) {
  const res = run.result;
  if (run.status === "queued" || run.status === "running")
    return <Callout tone="info" title="The AI is analysing this petition">Triage, research and citation verification are running. This page refreshes automatically.</Callout>;
  if (run.status === "failed")
    return <Callout tone="danger" title="The analysis failed">{run.error ?? "No recommendation was produced."} A human examiner will need to handle this petition.</Callout>;
  if (!res) return null;
  if (res.mode === "placeholder")
    return <Callout tone="warning" title="Placeholder result — not an AI recommendation">No regulations were retrieved and no model was used.</Callout>;

  const stub = (res.llm_models ?? []).some((m) => /stub|scripted|fake|mock/i.test(m));
  const none = res.position === "NO_DETERMINATION";
  const esc = res.escalation;
  const tri = res.triage;
  return (
    <div className="space-y-4">
      {stub && <Callout tone="warning" title="Produced by a stub / scripted model">Retrieval and citation checks are real, but the recommendation text was not written by a real AI model.</Callout>}
      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0">
          <CardTitle>AI recommendation <span className="font-normal text-muted-foreground">· not a decision</span></CardTitle>
          <RouteBadge route={res.route} noDetermination={none} />
        </CardHeader>
        <CardContent className="space-y-3">
          {none ? (
            <p className="text-sm">The system did not make a determination for this petition.</p>
          ) : (
            <>
              <div><p className="text-xs font-medium text-muted-foreground">Position</p><p className="mt-0.5 text-sm leading-relaxed">{res.position}</p></div>
              <div><p className="text-xs font-medium text-muted-foreground">Reasoning</p><p className="mt-0.5 text-sm leading-relaxed">{res.basis}</p></div>
            </>
          )}
          {(res.open_questions?.length ?? 0) > 0 && (
            <p className="rounded-md bg-warning-soft px-3 py-2 text-xs text-warning">
              This recommendation depends on {res.open_questions!.length} unresolved interpretation(s) that have not been confirmed (listed below). Treat the position above as a proposal, not as established rule.
            </p>
          )}
          {esc?.required && (
            <Callout tone="warning" title={`Escalated for human decision · ${titleCase(esc.reason)}`}>
              <p>{escalationText(esc.reason)}</p>
              {esc.detail && <p className="mt-1 opacity-80">{esc.detail}</p>}
            </Callout>
          )}
          {tri && audience === "examiner" && (
            <div className="rounded-md bg-muted/60 p-3">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium">Triage confidence</span>
                <span className="font-mono tabular-nums">{Math.round(tri.confidence * 100)}%</span>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-border" role="meter" aria-valuenow={Math.round(tri.confidence * 100)} aria-valuemin={0} aria-valuemax={100} aria-label="Triage confidence">
                <div className="h-full rounded-full bg-accent" style={{ width: `${Math.round(tri.confidence * 100)}%` }} />
              </div>
              <p className="mt-1.5 text-[11px] text-muted-foreground">How sure the triage agent is about what kind of petition this is. It is not the probability that the recommendation is correct.</p>
              {tri.flags.length > 0 && <p className="mt-1 text-xs text-warning">Flags: {tri.flags.join("; ")}</p>}
            </div>
          )}
        </CardContent>
      </Card>

      <Callout tone="info" title="A human examiner must review this petition">
        {audience === "student"
          ? "Nothing on this page is a university decision. An examiner will review your petition and record their own decision, which will appear below."
          : "This recommendation is advisory. Review the evidence and record your own decision below."}
      </Callout>

      <section aria-labelledby="ev-h">
        <h2 id="ev-h" className="mb-2 text-sm font-semibold">Regulatory evidence <span className="font-normal text-muted-foreground">· {res.citations.length} verified citation(s)</span></h2>
        {res.citations.length === 0 ? (
          <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            No citation was verified.{res.evidence_reviewed?.length ? ` Passages reviewed but not cited: ${res.evidence_reviewed.map((e) => `${e.clause_id} (p.${e.page})`).join(", ")}.` : " No regulation passages were retrieved."}
          </p>
        ) : <div className="space-y-3">{res.citations.map((c) => <CitationCard key={c.evidence_id + c.clause_id} c={c} />)}</div>}
      </section>

      {(res.open_questions?.length ?? 0) > 0 && (
        <details className="group rounded-lg border bg-warning-soft/40 p-4 text-sm open:bg-warning-soft/60">
          <summary className="flex cursor-pointer list-none items-center gap-2 font-semibold"><ShieldAlert className="size-4 text-warning" />Unresolved interpretations ({res.open_questions!.length}) — not verified</summary>
          <ul className="mt-3 space-y-2.5">
            {res.open_questions!.map((q) => <li key={q.id}><span className="font-semibold">{q.id} · {q.topic}.</span> <span className="text-muted-foreground">{q.text}</span></li>)}
          </ul>
        </details>
      )}
      {audience === "examiner" && (res.human_review_checklist?.length ?? 0) > 0 && (
        <details className="rounded-lg border p-4 text-sm">
          <summary className="cursor-pointer list-none font-semibold">Reviewer checklist</summary>
          <ul className="mt-3 list-disc space-y-1.5 pl-5 text-muted-foreground">{res.human_review_checklist!.map((c) => <li key={c}>{c}</li>)}</ul>
        </details>
      )}
    </div>
  );
}

export function DocumentList({ runId, documents }: { runId: string; documents: DocumentRecord[] }) {
  if (documents.length === 0) return <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">No supporting documents attached.</p>;
  return (
    <ul className="divide-y rounded-lg border">
      {documents.map((d) => (
        <li key={d.id} className="flex items-center gap-3 p-3 text-sm">
          <Paperclip className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium">{d.filename}</p>
            <p className="text-xs text-muted-foreground">{formatBytes(d.size)} · {formatDateTime(d.ts)} · sha256 <span className="font-mono">{d.sha256.slice(0, 10)}…</span></p>
          </div>
          <Button asChild variant="outline" size="sm"><a href={api.documentUrl(runId, d.id)} download={d.filename}>Download</a></Button>
        </li>
      ))}
    </ul>
  );
}

const MAX_BYTES = 2 * 1024 * 1024;
const ACCEPT = ".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg";

export function DocumentUploader({ runId, existing }: { runId: string; existing: number }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const remaining = 3 - existing;
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      for (const f of files) {
        if (f.size > MAX_BYTES) { toast.error(`${f.name}: larger than 2 MB`); continue; }
        try {
          await api.uploadDocument(runId, f);
          toast.success(`${f.name} uploaded`);
        } catch (e) {
          toast.error(`${f.name}: ${e instanceof ApiError ? e.message : "upload failed"}`);
        }
      }
    },
    onSettled: () => { setBusy(false); qc.invalidateQueries({ queryKey: ["run", runId] }); if (input.current) input.current.value = ""; },
  });
  return (
    <div className="rounded-lg border border-dashed p-4">
      <div className="flex flex-wrap items-center gap-3">
        <FileUp className="size-5 text-muted-foreground" aria-hidden />
        <div className="min-w-0 flex-1 text-sm">
          <p className="font-medium">Add supporting documents</p>
          <p className="text-xs text-muted-foreground">PDF, PNG or JPEG · up to 2 MB each · at most 3 per petition ({remaining > 0 ? `${remaining} left` : "limit reached"}). Stored for the examiner only; the AI does not read them.</p>
        </div>
        <input ref={input} id={`file-${runId}`} type="file" accept={ACCEPT} multiple className="sr-only" aria-label="Choose documents"
          onChange={(e) => { const fs = Array.from(e.target.files ?? []).slice(0, Math.max(remaining, 0)); if (fs.length) { setBusy(true); upload.mutate(fs); } }} />
        <Button type="button" variant="outline" size="sm" loading={busy} disabled={remaining <= 0} onClick={() => input.current?.click()}>Choose files</Button>
      </div>
    </div>
  );
}
