import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Gavel,
  Inbox,
  Search,
  ShieldCheck,
  UserCheck,
} from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Donut, HBar, TrendArea } from "@/components/petition/charts";
import {
  DecisionBadge, DocumentList, PageHeader, PipelineStepper, RecommendationPanel, RouteBadge, StatCard, StatusBadge,
} from "@/components/petition/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Callout, EmptyState, ErrorState, Skeleton } from "@/components/ui/feedback";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/authContext";
import { useDocumentTitle } from "@/lib/hooks";
import { useRun } from "@/lib/queries";
import type { ExaminerDecisionValue, RunSummary } from "@/lib/types";
import { formatDateTime, isTerminal, timeAgo, titleCase } from "@/lib/utils";

const needsReview = (r: RunSummary) => isTerminal(r.status) && !r.examiner_decision;

// ---------------------------------------------------------------- Examiner Dashboard
export function ExaminerDashboard() {
  useDocumentTitle("Examiner Dashboard");
  const { user } = useAuth();
  const [realOnly, setRealOnly] = useState(false);

  const runs = useQuery({
    queryKey: ["runs", "examiner", "pending", realOnly],
    queryFn: () => api.runs({ limit: 50, real_only: realOnly, awaiting_decision: true }),
    refetchInterval: 5000,
  });

  const totals = useQuery({
    queryKey: ["runs", "counts"],
    queryFn: () => api.runs({ limit: 1 }),
    refetchInterval: 15000,
  });

  const stats = useQuery({
    queryKey: ["stats", realOnly],
    queryFn: () => api.stats(realOnly),
    refetchInterval: 15000,
  });

  const pending = runs.data?.runs ?? [];
  const pendingTotal = runs.data?.matched ?? 0;
  const allCount = Object.values(totals.data?.counts ?? {}).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-6">
      {/* Executive Welcome & Mode Banner */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-[#292725] via-[#34312E] to-[#1E1C1A] p-6 md:p-8 text-[#F7F4EF] shadow-lg border border-[#3D3A36]">
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1.5">
            <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-[#E69A45]/15 text-[#E69A45] border border-[#E69A45]/30">
              <ShieldCheck className="size-3.5" />
              Academic Examination Board · Presiding Officer
            </div>
            <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight">
              Executive Review Dashboard
            </h1>
            <p className="text-xs md:text-sm text-[#B4ADA5] flex flex-wrap items-center gap-3 font-medium">
              <span>Examiner: <strong className="text-white">{user?.name || "Dr. Eleanor Vance"}</strong></span>
              <span>•</span>
              <span>ID: <strong className="font-mono text-[#E69A45]">{user?.user_id || "EXM2026001"}</strong></span>
              <span>•</span>
              <span>Authorized Decision Authority</span>
            </p>
          </div>

          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-[#B4ADA5] bg-[#1E1C1A] px-3 py-2 rounded-xl border border-[#3D3A36] cursor-pointer select-none">
              <input
                type="checkbox"
                className="size-4 accent-[#C66A32] rounded"
                checked={!realOnly}
                onChange={(e) => setRealOnly(!e.target.checked)}
              />
              <span>Include all runs</span>
            </label>

            <Button asChild className="bg-[#C66A32] hover:bg-[#B35922] text-white font-bold shadow-md">
              <Link to="/examiner/queue">
                <Inbox className="size-4 mr-1.5" />
                Review Queue ({pendingTotal})
              </Link>
            </Button>
          </div>
        </div>
      </div>

      {runs.isError && <ErrorState error={runs.error} onRetry={() => runs.refetch()} />}

      {realOnly && allCount > 0 && (stats.data?.runs_considered ?? 1) === 0 && (
        <Callout tone="info" title="Stub / scripted runs are hidden" className="mb-4">
          {allCount} petition(s) exist in the system, but none was answered by a real LLM provider. Uncheck "Include stub / load-test runs" above to inspect them.
        </Callout>
      )}

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Awaiting Human Decision"
          value={runs.isLoading ? "…" : pendingTotal}
          tone={pendingTotal > 0 ? "warning" : undefined}
          hint="AI finished, pending official ruling"
        />
        <StatCard
          label="Total Cases Evaluated"
          value={stats.data?.runs_considered ?? "…"}
          hint={realOnly ? "Answered by real LLM" : "Including benchmark stubs"}
        />
        <StatCard
          label="Referred to Committee"
          value={stats.data?.by_status.escalated ?? 0}
          hint="Special discretion required"
        />
        <StatCard
          label="Median Processing Latency"
          value={stats.data?.latency_seconds.p50 != null ? `${stats.data.latency_seconds.p50.toFixed(1)}s` : "—"}
          hint={stats.data?.latency_seconds.p95 != null ? `p95 ${stats.data.latency_seconds.p95.toFixed(1)}s` : "End-to-end"}
        />
      </div>

      {/* Main Review Section: Priority Queue & Status Distribution */}
      <div className="grid gap-6 lg:grid-cols-5">
        {/* Needs Review Priority List */}
        <Card className="lg:col-span-3 shadow-sm">
          <CardHeader className="pb-3 flex flex-row items-center justify-between">
            <div>
              <CardTitle className="text-base font-bold flex items-center gap-2">
                <Gavel className="size-4 text-amber-500" />
                Priority Cases Awaiting Your Ruling
              </CardTitle>
              <CardDescription className="text-xs">
                Cases with AI recommendation ready, ordered by arrival date
              </CardDescription>
            </div>
            {pendingTotal > 0 && (
              <Badge variant="outline" className="text-xs font-semibold border-amber-500/30 text-amber-600 bg-amber-500/10">
                {pendingTotal} Pending
              </Badge>
            )}
          </CardHeader>
          <CardContent>
            {runs.isLoading ? (
              <Skeleton className="h-44 rounded-xl" />
            ) : pending.length === 0 ? (
              <EmptyState icon={<Inbox />} title="No petitions currently awaiting decision">
                {realOnly
                  ? "All real-model petitions have been reviewed and determined."
                  : "Review queue is clear."}
              </EmptyState>
            ) : (
              <div className="space-y-3">
                <ul className="divide-y rounded-xl border overflow-hidden">
                  {pending.slice(0, 6).map((r) => (
                    <li key={r.run_id}>
                      <Link
                        to={`/examiner/review/${r.run_id}`}
                        className="flex items-center justify-between gap-3 px-4 py-3 text-sm transition-colors hover:bg-muted/60"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="truncate font-semibold text-foreground">
                            {titleCase(r.petition_type)} · {r.student_ref} · {r.course_code}
                          </p>
                          <p className="text-xs text-muted-foreground flex items-center gap-2 mt-0.5">
                            <span>{timeAgo(r.created_at)}</span>
                            {r.attendance_percentage != null && (
                              <>
                                <span>•</span>
                                <span className="font-mono font-medium text-foreground">{r.attendance_percentage}% attendance</span>
                              </>
                            )}
                          </p>
                        </div>
                        <div className="flex items-center gap-3">
                          <RouteBadge route={r.route} noDetermination={!r.route} />
                          <ArrowRight className="size-4 text-muted-foreground" aria-hidden />
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>

                {pendingTotal > 6 && (
                  <Button asChild variant="outline" size="sm" className="w-full text-xs">
                    <Link to="/examiner/queue">
                      View all {pendingTotal} pending cases in queue
                      <ArrowRight className="size-3.5 ml-1" />
                    </Link>
                  </Button>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Status Distribution Donut */}
        <Card className="lg:col-span-2 shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-bold">Case Status Distribution</CardTitle>
            <CardDescription className="text-xs">Outcomes across processed runs</CardDescription>
          </CardHeader>
          <CardContent>
            {stats.isLoading ? (
              <Skeleton className="h-48 rounded-xl" />
            ) : (
              <Donut data={stats.data?.by_status ?? {}} />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Second Row: Escalation Reasons & Infrastructure Readiness */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-bold">Escalation Reasons Breakdown</CardTitle>
            <CardDescription className="text-xs">Why the AI routed cases for special human review</CardDescription>
          </CardHeader>
          <CardContent>
            {stats.isLoading ? (
              <Skeleton className="h-48 rounded-xl" />
            ) : (
              <HBar data={stats.data?.escalation_reasons ?? {}} />
            )}
          </CardContent>
        </Card>

        <Card className="shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-bold">Daily Petition Influx</CardTitle>
            <CardDescription className="text-xs">Volume and escalation trends over time</CardDescription>
          </CardHeader>
          <CardContent>
            {stats.isLoading ? (
              <Skeleton className="h-48 rounded-xl" />
            ) : (
              <TrendArea data={stats.data?.by_day ?? {}} />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Examiner Review Queue
export function ExaminerQueue() {
  useDocumentTitle("Review Queue");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [decision, setDecision] = useState("");
  const [type, setType] = useState("");
  const [realOnly, setRealOnly] = useState(false);

  const q = useQuery({
    queryKey: ["runs", "queue", realOnly, status],
    queryFn: () => api.runs({ limit: 200, real_only: realOnly, status }),
    refetchInterval: 5000,
  });

  const rows = useMemo(
    () =>
      (q.data?.runs ?? []).filter((r) => {
        const matchesSearch =
          !search ||
          `${r.student_ref} ${r.run_id} ${r.course_code}`.toLowerCase().includes(search.toLowerCase());
        const matchesType = !type || r.petition_type === type;
        const matchesDecision =
          !decision ||
          (decision === "pending"
            ? needsReview(r)
            : decision === "decided"
            ? !!r.examiner_decision
            : r.examiner_decision === decision);
        return matchesSearch && matchesType && matchesDecision;
      }),
    [q.data, search, type, decision]
  );

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Examiner Portal"
        title="Comprehensive Review Queue"
        description="Filter and search all student submissions, view AI triage candidate positions, and issue decisions."
      />

      {/* Filters Card */}
      <Card className="shadow-sm">
        <CardContent className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5 items-end">
          <Field id="q" label="Search">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
              <Input
                id="q"
                className="pl-8"
                placeholder="Student, course or run ID…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </Field>

          <Field id="s" label="AI Status">
            <Select id="s" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All Statuses</option>
              <option value="running">In Processing</option>
              <option value="completed">Recommendation Ready</option>
              <option value="escalated">Escalated</option>
              <option value="failed">Processing Failed</option>
            </Select>
          </Field>

          <Field id="d" label="Examiner Ruling">
            <Select id="d" value={decision} onChange={(e) => setDecision(e.target.value)}>
              <option value="">All Decisions</option>
              <option value="pending">Awaiting Ruling</option>
              <option value="decided">Already Decided</option>
              <option value="accept-petition">Accepted</option>
              <option value="reject-petition">Rejected</option>
              <option value="request-more-information">Info Requested</option>
            </Select>
          </Field>

          <Field id="t" label="Category">
            <Select id="t" value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">All Categories</option>
              {["attendance", "re-evaluation", "re-registration", "medical-leave", "grade-grievance"].map((t) => (
                <option key={t} value={t}>
                  {titleCase(t)}
                </option>
              ))}
            </Select>
          </Field>

          <label className="flex items-center gap-2 pb-2 text-xs font-medium text-foreground cursor-pointer select-none">
            <input
              type="checkbox"
              className="size-4 accent-amber-500 rounded"
              checked={realOnly}
              onChange={(e) => setRealOnly(e.target.checked)}
            />
            Real LLM Runs Only
          </label>
        </CardContent>
      </Card>

      {q.isLoading ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState icon={<Inbox />} title="No petitions match these criteria" />
      ) : (
        <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
          <div className="hidden grid-cols-[1.4fr_1fr_1.1fr_1.3fr_1.3fr_auto] gap-3 border-b bg-muted/50 px-4 py-2.5 text-xs font-semibold text-muted-foreground lg:grid">
            <span>Case / Student</span>
            <span>Submitted</span>
            <span>AI Status</span>
            <span>AI Candidate Position</span>
            <span>Examiner Ruling</span>
            <span />
          </div>
          <ul className="divide-y divide-border/60">
            {rows.map((r) => (
              <li key={r.run_id}>
                <Link
                  to={`/examiner/review/${r.run_id}`}
                  className="grid gap-2 px-4 py-3.5 text-sm transition-colors hover:bg-muted/50 lg:grid-cols-[1.4fr_1fr_1.1fr_1.3fr_1.3fr_auto] lg:items-center lg:gap-3"
                >
                  <div className="min-w-0">
                    <p className="truncate font-semibold text-foreground">
                      {titleCase(r.petition_type)} · {r.student_ref}
                    </p>
                    <p className="truncate font-mono text-xs text-muted-foreground">
                      {r.run_id} · {r.course_code ?? "—"}
                    </p>
                  </div>
                  <span className="text-xs text-muted-foreground" title={formatDateTime(r.created_at)}>
                    {timeAgo(r.created_at)}
                  </span>
                  <span>
                    <StatusBadge status={r.status} />
                  </span>
                  <span>
                    {isTerminal(r.status) ? (
                      <RouteBadge route={r.route} noDetermination={!r.route} />
                    ) : (
                      <Badge variant="outline">—</Badge>
                    )}
                  </span>
                  <span>
                    <DecisionBadge decision={r.examiner_decision} />
                  </span>
                  <ArrowRight className="hidden size-4 text-muted-foreground lg:block" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
          <div className="border-t bg-muted/20 px-4 py-2.5 text-xs text-muted-foreground flex justify-between">
            <span>{rows.length} petition(s) displayed</span>
            {(q.data?.matched ?? 0) > (q.data?.runs.length ?? 0) && (
              <span>Showing newest {q.data?.runs.length} of {q.data?.matched} matches</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Decision Form Component
function DecisionForm({ runId, terminal }: { runId: string; terminal: boolean }) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const examinerName = user?.name || "Dr. Eleanor Vance";

  const [decision, setDecision] = useState<ExaminerDecisionValue | "">("");
  const [note, setNote] = useState("");
  const [touched, setTouched] = useState(false);

  const errors = {
    decision: decision ? "" : "Please select an official decision.",
    note: note.trim().length < 10 ? `Explain your reasoning (at least 10 characters, ${note.trim().length} so far)` : "",
  };

  const m = useMutation({
    mutationFn: () =>
      api.examinerDecision(runId, {
        decision: decision as ExaminerDecisionValue,
        note: note.trim(),
        examiner_label: examinerName,
      }),
    onSuccess: () => {
      toast.success("Examiner decision recorded and permanently attributed.");
      setNote("");
      setDecision("");
      setTouched(false);
      qc.invalidateQueries({ queryKey: ["run", runId] });
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not record decision"),
  });

  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    setTouched(true);
    if (Object.values(errors).some(Boolean)) return;
    m.mutate();
  };

  const options: { v: ExaminerDecisionValue; title: string; hint: string }[] = [
    { v: "accept-petition", title: "Accept Petition", hint: "Grant attendance condonation under regulations." },
    { v: "reject-petition", title: "Reject Petition", hint: "Shortage exceeds allowable condonation limit." },
    { v: "request-more-information", title: "Request More Info", hint: "Require supplemental medical or official records." },
  ];

  if (!terminal) {
    return (
      <Callout tone="info" title="AI Pipeline Running">
        Please wait until the automated agent triage and citation verification finishes before recording your decision.
      </Callout>
    );
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      {/* Officer attribution indicator */}
      <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-xs text-foreground flex items-center justify-between">
        <div className="flex items-center gap-2">
          <UserCheck className="size-4 text-amber-500" />
          <span>Attributed Examiner: <strong>{examinerName}</strong></span>
        </div>
        <span className="font-mono text-[11px] text-muted-foreground">{user?.user_id || "EXM2026001"}</span>
      </div>

      <fieldset className="space-y-2">
        <legend className="text-xs font-bold text-foreground uppercase tracking-wider">
          Official Ruling <span className="text-red-500">*</span>
        </legend>
        <div role="radiogroup" className="grid gap-2 sm:grid-cols-3">
          {options.map((o) => (
            <button
              key={o.v}
              type="button"
              role="radio"
              aria-checked={decision === o.v}
              onClick={() => setDecision(o.v)}
              className={`rounded-xl border p-3 text-left text-xs transition-all hover:bg-muted/60 ${
                decision === o.v
                  ? "border-[#C66A32] bg-[#C66A32]/10 ring-2 ring-[#C66A32]/30 shadow-sm"
                  : "border-border"
              }`}
            >
              <span className="block font-bold text-foreground">{o.title}</span>
              <span className="mt-1 block text-muted-foreground leading-relaxed">{o.hint}</span>
            </button>
          ))}
        </div>
        {touched && errors.decision && <p role="alert" className="text-xs font-medium text-red-500">{errors.decision}</p>}
      </fieldset>

      <Field
        id="note"
        label="Examiner Justification & Ruling Note"
        required
        hint="Recorded permanently in decision log and visible to the student. 10–1000 characters."
        error={touched ? errors.note : undefined}
      >
        <Textarea
          id="note"
          rows={4}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={1000}
          aria-invalid={touched && !!errors.note}
          placeholder="State the regulatory grounds, certificate assessment, or reason for this ruling…"
        />
      </Field>

      <Button
        type="submit"
        loading={m.isPending}
        className="w-full bg-[#C66A32] hover:bg-[#B35922] text-white font-bold shadow-md cursor-pointer"
      >
        <Gavel className="size-4 mr-1.5" />
        Record & Sign Official Examiner Decision
      </Button>
    </form>
  );
}

// ---------------------------------------------------------------- Examiner Review Suite
export function ExaminerReview() {
  const { id } = useParams();
  const q = useRun(id);
  const trace = useQuery({
    queryKey: ["trace", id],
    queryFn: () => api.trace(id!),
    enabled: !!q.data && isTerminal(q.data.status),
  });

  useDocumentTitle(`Review Case ${id ?? ""}`);

  if (q.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-1/2" />
        <Skeleton className="h-64 rounded-xl" />
      </div>
    );
  }

  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const run = q.data!;
  const p = run.petition;
  const t = trace.data;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Examiner Review Board"
        title={`${titleCase(run.petition_type)} · ${run.student_ref}`}
        description={`Case Tracking ID: ${run.run_id}`}
        actions={
          <Button asChild variant="outline" size="sm">
            <Link to="/examiner/queue">Back to Queue</Link>
          </Button>
        }
      />

      {/* Case Status & Stepper */}
      <div className="flex flex-wrap items-center gap-3 p-4 rounded-xl border bg-card shadow-sm">
        <StatusBadge status={run.status} />
        <div className="h-4 w-px bg-border hidden sm:block" />
        <PipelineStepper run={run} />
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        {/* Left: AI Assessment & Verbatim Citations (3 columns) */}
        <div className="space-y-6 lg:col-span-3">
          <Tabs defaultValue="recommendation">
            <TabsList className="w-full justify-start">
              <TabsTrigger value="recommendation">AI Regulatory Recommendation</TabsTrigger>
              <TabsTrigger value="pipeline">Multi-Agent Pipeline Trace</TabsTrigger>
            </TabsList>

            <TabsContent value="recommendation" className="mt-4">
              <RecommendationPanel run={run} audience="examiner" />
            </TabsContent>

            <TabsContent value="pipeline" className="mt-4">
              {!t ? (
                <p className="text-xs text-muted-foreground">
                  {trace.isError ? "Pipeline trace unavailable." : "Trace data appears once execution finishes."}
                </p>
              ) : (
                <div className="space-y-4 text-xs">
                  <div className="p-3 rounded-xl border bg-muted/30 flex flex-wrap gap-4 text-muted-foreground">
                    <span>Duration: <strong className="text-foreground">{t.total_seconds}s</strong></span>
                    <span>•</span>
                    <span>Events: <strong className="text-foreground">{t.event_count}</strong></span>
                    <span>•</span>
                    <span>LLM Retries: <strong className="text-foreground">{t.retry_count}</strong></span>
                    <span>•</span>
                    <span>Correlation: <span className="font-mono text-foreground">{t.correlation_id}</span></span>
                  </div>

                  <div className="overflow-x-auto rounded-xl border">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-muted/60 text-muted-foreground font-semibold">
                        <tr>
                          {["Agent", "Runs", "Failures", "Duration", "LLM Calls", "Tool Calls"].map((h) => (
                            <th key={h} className="px-3 py-2.5">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y">
                        {Object.entries(t.agents).map(([a, v]) => (
                          <tr key={a}>
                            <td className="px-3 py-2.5 font-bold">{titleCase(a)}</td>
                            <td className="px-3 py-2.5">{v.runs}</td>
                            <td className="px-3 py-2.5 text-red-500 font-medium">{v.failures}</td>
                            <td className="px-3 py-2.5">{v.seconds}s</td>
                            <td className="px-3 py-2.5">{v.llm_calls}</td>
                            <td className="px-3 py-2.5">{v.tool_calls}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </TabsContent>
          </Tabs>
        </div>

        {/* Right: Submitted Petition & Decision Interface (2 columns) */}
        <div className="space-y-6 lg:col-span-2">
          {/* Submitted Data */}
          {p && (
            <Card className="shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-bold">Student Submission</CardTitle>
                <CardDescription className="text-xs">Self-declared petition fields</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-xs">
                  <dt className="text-muted-foreground">Programme</dt>
                  <dd className="font-semibold text-foreground">{p.program} ({p.admission_batch})</dd>
                  <dt className="text-muted-foreground">Course Code</dt>
                  <dd className="font-semibold text-foreground">{p.course_code} · Semester {p.semester}</dd>
                  <dt className="text-muted-foreground">Attendance</dt>
                  <dd className="font-semibold font-mono text-foreground">
                    {p.attendance_percentage ?? "—"}% {p.classes_held ? `(${p.classes_attended}/${p.classes_held} classes)` : ""}
                  </dd>
                  <dt className="text-muted-foreground">Reason</dt>
                  <dd className="font-semibold text-foreground">{titleCase(p.reason_category)}</dd>
                  <dt className="text-muted-foreground">Medical Proof</dt>
                  <dd className="font-semibold text-foreground">{titleCase(p.medical_documentation)}</dd>
                </dl>
                <div className="border-t pt-2.5">
                  <p className="text-[11px] font-semibold text-muted-foreground mb-1">Student Narrative:</p>
                  <p className="text-xs text-foreground leading-relaxed bg-muted/40 p-2.5 rounded-lg border">
                    {p.petition_text}
                  </p>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Supporting Documents */}
          <Card className="shadow-sm">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-bold flex items-center justify-between">
                <span>Attached Evidence</span>
                <Badge variant="outline" className="text-[10px]">{run.documents.length} files</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <DocumentList runId={run.run_id} documents={run.documents} />
            </CardContent>
          </Card>

          {/* Decision Recording Form */}
          <Card className="border-amber-500/30 shadow-md">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-bold flex items-center gap-2">
                <Gavel className="size-4 text-amber-500" />
                Examiner Determination Suite
              </CardTitle>
              <CardDescription className="text-xs">
                Your ruling is stored permanently and separate from the AI recommendation.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <DecisionForm runId={run.run_id} terminal={isTerminal(run.status)} />
            </CardContent>
          </Card>

          {/* Decision History */}
          <Card className="shadow-sm">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-bold">Recorded Decision History</CardTitle>
            </CardHeader>
            <CardContent>
              {run.examiner_decisions.length === 0 ? (
                <p className="text-xs text-muted-foreground">No examiner decisions recorded yet for this case.</p>
              ) : (
                <ol className="space-y-3">
                  {[...run.examiner_decisions].reverse().map((d) => (
                    <li key={d.id} className="rounded-xl border p-3 text-xs space-y-1.5 bg-muted/20">
                      <div className="flex items-center justify-between">
                        <DecisionBadge decision={d.decision} />
                        <span className="text-[10px] text-muted-foreground">{formatDateTime(d.ts)}</span>
                      </div>
                      <p className="font-medium text-foreground leading-relaxed">{d.note}</p>
                      <p className="text-[11px] text-muted-foreground border-t pt-1 mt-1">
                        Signed by <strong>{d.examiner_label}</strong>
                      </p>
                    </li>
                  ))}
                </ol>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
