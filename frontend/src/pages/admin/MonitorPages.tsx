import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Donut, HBar, ValueBars } from "@/components/petition/charts";
import { PageHeader, StatCard } from "@/components/petition/shared";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Callout, EmptyState, ErrorState, Skeleton } from "@/components/ui/feedback";
import { api } from "@/lib/api";
import { useDocumentTitle } from "@/lib/hooks";
import { formatDateTime, titleCase } from "@/lib/utils";

function Health({ ok, label, detail }: { ok: "ok" | "warn" | "bad"; label: string; detail: string }) {
  const c = { ok: "bg-success", warn: "bg-warning", bad: "bg-danger" }[ok];
  return (
    <li className="flex items-center justify-between gap-3 py-2.5 text-sm">
      <span className="flex items-center gap-2"><span className={`size-2 rounded-full ${c}`} aria-hidden />{label}</span>
      <span className="font-mono text-xs text-muted-foreground">{detail}</span>
    </li>
  );
}

export function SystemOverviewPage() {
  useDocumentTitle("System overview");
  const [realOnly, setRealOnly] = useState(false);
  const ready = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 10000, retry: false });
  const sys = useQuery({ queryKey: ["system"], queryFn: api.system, refetchInterval: 10000 });
  const corpus = useQuery({ queryKey: ["corpus"], queryFn: api.corpus, refetchInterval: 30000 });
  const stats = useQuery({ queryKey: ["stats", realOnly], queryFn: () => api.stats(realOnly), refetchInterval: 15000 });
  const agents = useQuery({ queryKey: ["agents", realOnly], queryFn: () => api.agentStats(realOnly), refetchInterval: 15000 });
  const allRuns = useQuery({ queryKey: ["runs", "counts"], queryFn: () => api.runs({ limit: 1 }), refetchInterval: 15000 });
  const totalRuns = Object.values(allRuns.data?.counts ?? {}).reduce((a, b) => a + b, 0);
  const c = ready.data?.checks;
  const s = stats.data;
  const failures = s?.by_status.failed ?? 0;
  return (
    <>
      <PageHeader eyebrow="System" title="System overview" description="Live health of the queue, workers, model provider and retrieval, plus processing statistics. Everything here is read from the running backend."
        actions={
          <label className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
            <input type="checkbox" className="size-4 accent-[hsl(var(--accent))]" checked={!realOnly} onChange={(e) => setRealOnly(!e.target.checked)} />
            Include stub / load-test runs
          </label>
        } />
      {ready.isError && <div className="mb-4"><ErrorState error={ready.error} onRetry={() => ready.refetch()} /></div>}
      {c && c.degraded !== "none" && <Callout tone="warning" title="Degraded" className="mb-4">{c.degraded}</Callout>}
      {realOnly && s && s.runs_considered === 0 && totalRuns > 0 && (
        <Callout tone="info" title="Stub / scripted runs are hidden" className="mb-4">
          {totalRuns} petition(s) exist but none was answered by a real model, so the default view is empty. Tick “Include stub / load-test runs” to see them.
        </Callout>
      )}
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Total petitions" value={s?.runs_considered ?? "…"} hint={realOnly ? "answered by a real model" : "all runs incl. stub"} />
        <StatCard label="Pending in queue" value={sys.data?.queue.queued ?? "—"} hint={sys.data?.queue.started != null ? `${sys.data.queue.started} running now` : undefined} />
        <StatCard label="Completed + escalated" value={s ? (s.by_status.completed ?? 0) + (s.by_status.escalated ?? 0) : "…"} hint={s ? `${s.by_status.escalated ?? 0} escalated` : undefined} />
        <StatCard label="Failed runs" value={s ? failures : "…"} tone={failures ? "danger" : "success"} hint={sys.data?.queue.failed_jobs != null ? `${sys.data.queue.failed_jobs} failed queue jobs` : undefined} />
      </div>
      <div className="mb-5 grid gap-5 lg:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Service health</CardTitle></CardHeader>
          <CardContent>
            {ready.isLoading ? <Skeleton className="h-40" /> : c ? (
              <ul className="divide-y">
                <Health ok={c.redis === "ok" ? "ok" : "bad"} label="Queue (Redis)" detail={c.redis} />
                <Health ok={c.database === "ok" ? "ok" : "bad"} label="Database (SQLite)" detail={c.database} />
                <Health ok={c.chroma === "ok" ? "ok" : "bad"} label="Vector index (Chroma)" detail={c.chroma} />
                <Health ok={c.workers && c.workers !== "0" ? "ok" : "bad"} label="Workers" detail={c.workers} />
                <Health ok={c.llm === "configured" ? "ok" : "warn"} label="LLM provider" detail={sys.data?.llm.model ?? c.llm} />
                <Health ok={c.llm_breaker === "closed" ? "ok" : c.llm_breaker === "half-open" ? "warn" : "bad"} label="LLM circuit breaker" detail={c.llm_breaker} />
              </ul>
            ) : <p className="text-sm text-muted-foreground">Health unavailable.</p>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Retrieval corpus</CardTitle><CardDescription>What the research agent can search</CardDescription></CardHeader>
          <CardContent className="space-y-2 text-sm">
            {corpus.isLoading ? <Skeleton className="h-32" /> : corpus.data ? (
              <>
                <p className="flex items-center justify-between"><span className="text-muted-foreground">Status</span><Badge tone={corpus.data.ready ? "success" : "warning"} dot>{corpus.data.ready ? "Ready" : "Not ready"}</Badge></p>
                <p className="flex justify-between"><span className="text-muted-foreground">Chunks indexed</span><span className="font-mono">{corpus.data.chunks_indexed}</span></p>
                <p className="flex justify-between"><span className="text-muted-foreground">Documents</span><span className="font-mono">{corpus.data.documents_indexed}</span></p>
                <p className="flex justify-between"><span className="text-muted-foreground">Last ingest</span><span className="font-mono text-xs">{formatDateTime(corpus.data.last_ingest_at)}</span></p>
                <p className="flex justify-between"><span className="text-muted-foreground">Verified passages</span><span className="font-mono">{Object.values(corpus.data.verified_passages).filter(Boolean).length}/{Object.keys(corpus.data.verified_passages).length}</span></p>
                <Callout tone="warning" className="!mt-3" title={`Difficult case: ${titleCase(corpus.data.difficult_case.status)}`}>Examination bye-laws, the official source URL and several interpretations are not verified.</Callout>
              </>
            ) : <p className="text-sm text-muted-foreground">Corpus status unavailable.</p>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Provider and limits</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            {sys.isLoading ? <Skeleton className="h-32" /> : sys.data ? (
              <>
                <p className="flex justify-between"><span className="text-muted-foreground">Model</span><span className="font-mono text-xs">{sys.data.llm.model ?? "not configured"}</span></p>
                <p className="flex justify-between"><span className="text-muted-foreground">Fallback provider</span><span>{sys.data.llm.fallback_configured ? "configured" : "none"}</span></p>
                <p className="flex justify-between"><span className="text-muted-foreground">Max run time</span><span className="font-mono">{sys.data.limits.max_run_seconds}s</span></p>
                <p className="flex justify-between"><span className="text-muted-foreground">Rate limit</span><span className="font-mono">{sys.data.limits.rate_limit_requests}/{sys.data.limits.rate_limit_window_seconds}s</span></p>
                <p className="flex justify-between"><span className="text-muted-foreground">Retrieval cache</span><span>{sys.data.limits.cache_enabled ? "on" : "off"}</span></p>
                <p className="flex justify-between"><span className="text-muted-foreground">Tokens used</span><span className="font-mono text-xs">{s ? `${s.tokens.prompt.toLocaleString()} in / ${s.tokens.completion.toLocaleString()} out` : "…"}</span></p>
              </>
            ) : <p className="text-sm text-muted-foreground">Unavailable.</p>}
          </CardContent>
        </Card>
      </div>
      <div className="grid gap-5 lg:grid-cols-2">
        <Card><CardHeader><CardTitle>Petition categories</CardTitle></CardHeader><CardContent>{stats.isLoading ? <Skeleton className="h-48" /> : <Donut data={s?.by_type ?? {}} />}</CardContent></Card>
        <Card><CardHeader><CardTitle>Status distribution</CardTitle></CardHeader><CardContent>{stats.isLoading ? <Skeleton className="h-48" /> : <Donut data={s?.by_status ?? {}} />}</CardContent></Card>
        <Card><CardHeader><CardTitle>Agent performance</CardTitle><CardDescription>Mean seconds per execution{agents.data ? ` · last ${agents.data.runs_considered} runs` : ""}</CardDescription></CardHeader>
          <CardContent>
            {agents.isLoading ? <Skeleton className="h-48" /> : <ValueBars unit="s" rows={Object.entries(agents.data?.agents ?? {}).map(([n, a]) => ({ name: n, value: a.mean_seconds }))} />}
            {agents.data && Object.keys(agents.data.agents).length > 0 && (
              <ul className="mt-3 grid gap-1 text-xs text-muted-foreground sm:grid-cols-3">{Object.entries(agents.data.agents).map(([n, a]) => <li key={n}><b className="text-foreground">{titleCase(n)}</b>: {a.executions} runs, {a.failures} failed</li>)}</ul>
            )}
          </CardContent></Card>
        <Card><CardHeader><CardTitle>Errors and escalation reasons</CardTitle><CardDescription>Latency: p50 {s?.latency_seconds.p50 ?? "—"}s · p95 {s?.latency_seconds.p95 ?? "—"}s (n={s?.latency_seconds.n ?? 0})</CardDescription></CardHeader><CardContent>{stats.isLoading ? <Skeleton className="h-48" /> : <HBar data={s?.escalation_reasons ?? {}} />}</CardContent></Card>
      </div>
    </>
  );
}

export function EvaluationPage() {
  useDocumentTitle("Evaluation");
  const q = useQuery({ queryKey: ["evaluation"], queryFn: api.evaluation });
  return (
    <>
      <PageHeader eyebrow="System" title="Evaluation" description="Reproducible evaluation reports. Scripted-model runs test the safety machinery; only real-model runs say anything about an LLM." />
      {q.isLoading ? <Skeleton className="h-64" /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} />
        : !q.data!.reports.length ? <EmptyState title="No evaluation report found">Run: python -m triage.evaluation.run --mode scripted</EmptyState>
          : (
            <div className="space-y-5">
              {q.data!.reports.map((r) => {
                const scripted = r.meta.mode === "scripted";
                const rows = Object.entries(r.metrics);
                return (
                  <Card key={r.file}>
                    <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0">
                      <div><CardTitle>{r.file}</CardTitle><CardDescription>{r.meta.scenario_count} scenarios · {formatDateTime(r.meta.generated_at)} · prompt {r.meta.research_prompt_version}</CardDescription></div>
                      <Badge tone={scripted ? "warning" : "info"}>{scripted ? "Scripted model" : `Real LLM · ${r.meta.model}`}</Badge>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <Callout tone={scripted ? "warning" : "info"} title="How to read these numbers">{r.meta.interpretation}</Callout>
                      <ValueBars rows={rows.map(([k, v]) => ({ name: k, value: v.value == null ? null : Math.round(v.value * 1000) / 1000 }))} height={240} />
                      <div className="overflow-x-auto rounded-lg border"><table className="w-full text-left text-sm"><thead className="bg-muted/50 text-xs text-muted-foreground"><tr><th className="px-3 py-2 font-medium">Metric</th><th className="px-3 py-2 font-medium">Value</th><th className="px-3 py-2 font-medium">n</th></tr></thead>
                        <tbody>{rows.map(([k, v]) => <tr key={k} className="border-t"><td className="px-3 py-2">{titleCase(k)}</td><td className="px-3 py-2 font-mono">{v.value == null ? "unavailable" : v.value.toFixed(3)}</td><td className="px-3 py-2 font-mono">{v.n}</td></tr>)}</tbody></table></div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}
    </>
  );
}
