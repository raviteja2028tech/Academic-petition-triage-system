import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpen,
  Building2,
  Calendar,
  CheckCircle2,
  Clock,
  FilePlus2,
  GraduationCap,
  HelpCircle,
  Info,
  Mail,
  Shield,
  User,
  UserCheck,
} from "lucide-react";
import { Fragment, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import {
  DecisionBadge, DocumentList, DocumentUploader, PageHeader, PipelineStepper, RecommendationPanel, StatCard, StatusBadge,
} from "@/components/petition/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Callout, EmptyState, ErrorState, Skeleton } from "@/components/ui/feedback";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/authContext";
import { useDocumentTitle } from "@/lib/hooks";
import { useRun } from "@/lib/queries";
import type { PetitionPayload, PetitionType, RunSummary } from "@/lib/types";
import { formatDateTime, timeAgo, titleCase } from "@/lib/utils";

const REF_RE = /^(SYN-\d{6}|STU\d{7})$/;

function PetitionRows({ runs }: { runs: RunSummary[] }) {
  return (
    <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
      <div className="hidden grid-cols-[1.3fr_1fr_1.1fr_1.3fr_auto] gap-3 border-b bg-muted/50 px-4 py-2.5 text-xs font-semibold text-muted-foreground md:grid">
        <span>Petition Case</span>
        <span>Submitted</span>
        <span>AI Assessment</span>
        <span>Examiner Ruling</span>
        <span />
      </div>
      <ul className="divide-y divide-border/60">
        {runs.map((r) => (
          <li key={r.run_id}>
            <Link
              to={`/student/petitions/${r.run_id}`}
              className="grid gap-2 px-4 py-3.5 text-sm transition-colors hover:bg-muted/50 md:grid-cols-[1.3fr_1fr_1.1fr_1.3fr_auto] md:items-center md:gap-3"
            >
              <div className="min-w-0">
                <p className="truncate font-semibold text-foreground">
                  {titleCase(r.petition_type)} · {r.course_code ?? "—"}
                </p>
                <p className="truncate font-mono text-xs text-muted-foreground">{r.run_id}</p>
              </div>
              <span className="text-xs text-muted-foreground" title={formatDateTime(r.created_at)}>
                {timeAgo(r.created_at)}
              </span>
              <span>
                <StatusBadge status={r.status} />
              </span>
              <span>
                <DecisionBadge decision={r.examiner_decision} />
              </span>
              <ArrowRight className="hidden size-4 text-muted-foreground md:block" aria-hidden />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

function useMyRuns(studentRef: string) {
  return useQuery({
    queryKey: ["runs", "student", studentRef],
    queryFn: () => api.runs({ student_ref: studentRef, limit: 100 }),
    enabled: REF_RE.test(studentRef),
    refetchInterval: (q) => (q.state.data?.runs.some((r) => r.status === "queued" || r.status === "running") ? 3000 : false),
  });
}

// ---------------------------------------------------------------- Student Dashboard
export function StudentHome() {
  useDocumentTitle("Student Dashboard");
  const { user } = useAuth();
  const studentRef = user?.user_id || "STU2026001";
  const q = useMyRuns(studentRef);

  const runs = q.data?.runs ?? [];
  const pendingHuman = runs.filter((r) => !r.examiner_decision).length;
  const completed = runs.filter((r) => r.examiner_decision === "accept-petition").length;
  const escalated = runs.filter((r) => r.status === "escalated" || r.examiner_decision === "request-more-information").length;

  return (
    <div className="space-y-6">
      {/* Personalized Welcome Header */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-[#C66A32] via-[#A85020] to-[#292725] p-6 md:p-8 text-white shadow-lg">
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1.5">
            <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-white/15 backdrop-blur text-white border border-white/20">
              <GraduationCap className="size-3.5" />
              Student Academic Portal
            </div>
            <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight">
              Welcome back, {user?.name || "Student"}
            </h1>
            <p className="text-xs md:text-sm text-amber-100/90 flex flex-wrap items-center gap-2.5 font-medium">
              <span>ID: <strong className="font-mono text-white">{studentRef}</strong></span>
              {user?.usn && (
                <>
                  <span>•</span>
                  <span>USN: <strong className="font-mono text-white">{user.usn}</strong></span>
                </>
              )}
              <span>•</span>
              <span>{user?.branch || "Computer Science & Engineering"}</span>
              <span>•</span>
              <span>Semester {user?.semester ?? 6} (Sec {user?.section ?? "A"})</span>
            </p>
          </div>

          <div className="flex items-center gap-3">
            <Button asChild size="lg" className="bg-white text-[#C66A32] hover:bg-white/95 font-semibold shadow-md gap-2">
              <Link to="/student/new">
                <FilePlus2 className="size-4" />
                Submit New Petition
              </Link>
            </Button>
          </div>
        </div>
      </div>

      {/* Advisory Banner */}
      <div className="flex items-start gap-3 p-3.5 rounded-xl border bg-brand/5 border-brand/20 text-xs text-foreground">
        <Info className="size-4 text-brand shrink-0 mt-0.5" />
        <div className="leading-relaxed">
          <strong>Advisory Triage Notice:</strong> The AI engine extracts clauses from university regulations and prepares an evidence package. All formal determinations are officially signed by a designated University Examination Officer.
        </div>
      </div>

      {/* Real Statistics Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Total Petitions"
          value={q.isLoading ? "…" : runs.length}
          hint="All submissions on file"
        />
        <StatCard
          label="Awaiting Board Review"
          value={q.isLoading ? "…" : pendingHuman}
          tone={pendingHuman > 0 ? "warning" : undefined}
          hint="Pending examiner ruling"
        />
        <StatCard
          label="Accepted Petitions"
          value={q.isLoading ? "…" : completed}
          tone="success"
          hint="Condonation approved"
        />
        <StatCard
          label="Under Special Review"
          value={q.isLoading ? "…" : escalated}
          hint="Referred to Committee"
        />
      </div>

      {/* Active Petitions & Timeline Grid */}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold text-foreground">Recent Petition Activity</h2>
            {runs.length > 5 && (
              <Button asChild variant="ghost" size="sm" className="text-xs">
                <Link to="/student/petitions">View All ({runs.length})<ArrowRight className="size-3.5 ml-1" /></Link>
              </Button>
            )}
          </div>

          {q.isLoading ? (
            <Skeleton className="h-44 rounded-xl" />
          ) : q.isError ? (
            <ErrorState error={q.error} onRetry={() => q.refetch()} />
          ) : runs.length === 0 ? (
            <EmptyState
              icon={<FilePlus2 />}
              title="No petitions filed yet"
              action={
                <Button asChild className="bg-brand text-white">
                  <Link to="/student/new">Submit Your First Petition</Link>
                </Button>
              }
            >
              Academic shortage requests submitted under reference {studentRef} will appear here with live AI verification updates.
            </EmptyState>
          ) : (
            <PetitionRows runs={runs.slice(0, 5)} />
          )}
        </div>

        {/* Workflow Guidance Card */}
        <div className="space-y-4">
          <Card className="shadow-sm">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-bold flex items-center gap-2">
                <Clock className="size-4 text-brand" />
                How Petitions Are Processed
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ol className="space-y-3.5 text-xs">
                {[
                  { title: "1. Intake & Quarantine Guard", desc: "Your submission is validated against academic data contracts and stored securely." },
                  { title: "2. Triple-Agent LangGraph", desc: "Triage Agent assesses eligibility, Research Agent searches university regulations, Verifier Agent verifies verbatim citations." },
                  { title: "3. Official Human Determination", desc: "An appointed Examiner examines the evidence and records a final binding decision." },
                ].map((s) => (
                  <li key={s.title} className="flex gap-2.5">
                    <span className="size-5 rounded-full bg-muted flex items-center justify-center font-bold text-[10px] shrink-0 mt-0.5">
                      ✓
                    </span>
                    <div>
                      <p className="font-semibold text-foreground">{s.title}</p>
                      <p className="text-muted-foreground leading-relaxed mt-0.5">{s.desc}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>

          <Card className="bg-slate-50 dark:bg-slate-900/40 shadow-sm border-dashed">
            <CardContent className="p-4 space-y-2 text-xs">
              <div className="flex items-center gap-2 font-semibold text-foreground">
                <HelpCircle className="size-4 text-brand" />
                Medical Certificate Regulations
              </div>
              <p className="text-muted-foreground leading-relaxed">
                Attendance condonation between 75% and 85% requires a certified medical certificate or official documentation. Upload supporting files directly when submitting.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- My Petitions History
export function MyPetitions() {
  useDocumentTitle("My Petitions");
  const { user } = useAuth();
  const studentRef = user?.user_id || "STU2026001";
  const [status, setStatus] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const q = useMyRuns(studentRef);

  const runs = (q.data?.runs ?? []).filter((r) => {
    const matchStatus = !status || r.status === status;
    const matchSearch =
      !searchTerm ||
      r.course_code?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      r.run_id.toLowerCase().includes(searchTerm.toLowerCase());
    return matchStatus && matchSearch;
  });

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Student Portal"
        title="Petition Submission History"
        description={`All academic petitions filed under authenticated student ID ${studentRef}.`}
        actions={
          <Button asChild className="bg-brand text-white">
            <Link to="/student/new">
              <FilePlus2 className="size-4" />
              New Petition
            </Link>
          </Button>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="lg:col-span-3">
          <Input
            placeholder="Search by course code (e.g. CS101) or run ID…"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full text-sm"
          />
        </div>
        <div>
          <Select id="statusFilter" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All Statuses</option>
            <option value="running">In Processing</option>
            <option value="completed">Recommendation Ready</option>
            <option value="escalated">Escalated</option>
            <option value="failed">Processing Failed</option>
          </Select>
        </div>
      </div>

      {q.isLoading ? (
        <Skeleton className="h-56 rounded-xl" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : runs.length === 0 ? (
        <EmptyState title="No petitions found">
          {searchTerm || status
            ? "No petitions match your active search filters."
            : "You have not submitted any petitions yet."}
        </EmptyState>
      ) : (
        <PetitionRows runs={runs} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------- New Petition Form
const TYPES: { id: PetitionType; label: string; supported: boolean; blurb: string }[] = [
  { id: "attendance", label: "Attendance Shortage", supported: true, blurb: "Condonation under Regulation 25OB10.0(5) for medical/authorized grounds." },
  { id: "re-evaluation", label: "Re-evaluation", supported: false, blurb: "Grade recheck. Escalates directly to human examination board." },
  { id: "re-registration", label: "Re-registration", supported: false, blurb: "Course re-enrollment exception." },
  { id: "medical-leave", label: "Medical Leave of Absence", supported: false, blurb: "Term postponement on medical grounds." },
  { id: "grade-grievance", label: "Grade Grievance", supported: false, blurb: "Evaluation dispute. Escalates to Faculty Review Board." },
];

interface FormState {
  student_ref: string;
  program: string;
  admission_batch: string;
  course_code: string;
  semester: string;
  petition_type: PetitionType;
  classes_held: string;
  classes_attended: string;
  reason_category: PetitionPayload["reason_category"];
  medical_documentation: PetitionPayload["medical_documentation"];
  petition_text: string;
}

function validate(f: FormState): Record<string, string> {
  const e: Record<string, string> = {};
  if (!REF_RE.test(f.student_ref)) e.student_ref = "Use the format SYN-000123 (or STU2026001)";
  if (f.program.trim().length < 2) e.program = "Enter your programme";
  if (!/^\d{4}-\d{2}$/.test(f.admission_batch)) e.admission_batch = "Use the format 2025-26";
  if (!/^[A-Za-z0-9]{3,12}$/.test(f.course_code)) e.course_code = "3–12 letters or digits, e.g. CS101";
  const sem = Number(f.semester);
  if (!Number.isInteger(sem) || sem < 1 || sem > 8) e.semester = "Between 1 and 8";
  if (f.petition_type === "attendance") {
    const h = Number(f.classes_held), a = Number(f.classes_attended);
    if (!f.classes_held || !Number.isInteger(h) || h < 1 || h > 1000) e.classes_held = "Enter classes held (1–1000)";
    if (f.classes_attended === "" || !Number.isInteger(a) || a < 0) e.classes_attended = "Enter classes attended";
    else if (!e.classes_held && a > h) e.classes_attended = "Cannot exceed classes held";
  }
  const n = f.petition_text.trim().length;
  if (n < 20) e.petition_text = `At least 20 characters (${n} so far)`;
  if (n > 2000) e.petition_text = "At most 2000 characters";
  return e;
}

export function NewPetition() {
  useDocumentTitle("Submit Petition");
  const navigate = useNavigate();
  const { user } = useAuth();
  const defaultRef = user?.user_id || "";

  const [f, setF] = useState<FormState>({
    student_ref: defaultRef,
    program: user?.branch || "Computer Science and Engineering",
    admission_batch: "2025-26",
    course_code: "",
    semester: user?.semester ? String(user.semester) : "3",
    petition_type: "attendance",
    classes_held: "",
    classes_attended: "",
    reason_category: "medical",
    medical_documentation: "certificate",
    petition_text: "",
  });

  const [touched, setTouched] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [files, setFiles] = useState<File[]>([]);
  const [accepted, setAccepted] = useState<{ run_id: string; fp: string } | null>(null);

  const errors = useMemo(() => ({ ...validate(f), ...serverErrors }), [f, serverErrors]);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => {
    setF((p) => ({ ...p, [k]: v }));
    setServerErrors((s) => {
      const { [k]: _drop, ...rest } = s;
      return rest;
    });
  };

  const pct =
    f.petition_type === "attendance" && Number(f.classes_held) > 0 && f.classes_attended !== ""
      ? Math.round((1000 * Number(f.classes_attended)) / Number(f.classes_held)) / 10
      : null;

  const fp = JSON.stringify(f);
  const err = (k: string) => (touched ? errors[k] : undefined);

  const submit = useMutation({
    mutationFn: async () => {
      const payload: PetitionPayload = {
        student_ref: f.student_ref,
        program: f.program.trim(),
        admission_batch: f.admission_batch,
        petition_type: f.petition_type,
        course_code: f.course_code,
        semester: Number(f.semester),
        reason_category: f.reason_category,
        medical_documentation: f.medical_documentation,
        petition_text: f.petition_text.trim(),
        ...(f.petition_type === "attendance"
          ? {
              classes_held: Number(f.classes_held),
              classes_attended: Number(f.classes_attended),
              attendance_percentage: pct ?? undefined,
            }
          : {}),
      };
      const res = await api.submit(payload);
      let failed = 0;
      for (const file of files) {
        try {
          await api.uploadDocument(res.run_id, file);
        } catch {
          failed += 1;
        }
      }
      if (failed) toast.warning(`${failed} document(s) could not be uploaded. You can attach them on the tracking page.`);
      return res;
    },
    onSuccess: (res) => {
      setAccepted({ run_id: res.run_id, fp });
      toast.success("Petition successfully submitted and queued for AI analysis.");
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 422) {
        const m: Record<string, string> = {};
        e.fieldErrors.forEach((x) => {
          m[x.field.replace(/^body\./, "")] = x.message;
        });
        setServerErrors(m);
        toast.error("The server rejected some fields. Please correct them.");
      } else if (e instanceof ApiError && e.status === 429) {
        toast.error(`Rate limit exceeded. Try again in ${e.retryAfter ?? "a few"} seconds.`);
      } else {
        toast.error(e instanceof Error ? e.message : "Submission failed");
      }
    },
  });

  const onSubmit = (ev: FormEvent) => {
    ev.preventDefault();
    setTouched(true);
    if (Object.keys(validate(f)).length) {
      toast.error("Please fix the highlighted form errors");
      return;
    }
    if (accepted?.fp === fp) {
      toast.info("This exact petition was already submitted.");
      return;
    }
    submit.mutate();
  };

  if (accepted) {
    return (
      <div className="space-y-6 max-w-xl mx-auto py-6">
        <PageHeader eyebrow="Student Portal" title="Petition Confirmation" />
        <Card className="shadow-lg border-2 border-emerald-500/20 text-center animate-fadeIn">
          <CardContent className="space-y-4 p-8">
            <div className="size-16 rounded-full bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 mx-auto flex items-center justify-center border border-emerald-200">
              <CheckCircle2 className="size-8" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-foreground">Petition Accepted & Queued</h2>
              <p className="mt-1 font-mono text-sm font-semibold text-brand">{accepted.run_id}</p>
            </div>
            <p className="text-xs md:text-sm text-muted-foreground leading-relaxed">
              Your petition is now being processed by the autonomous triple-agent pipeline (Triage, Research, Citation Verifier). After the recommendation is prepared, an examiner will review and record the official determination.
            </p>
            <div className="pt-2 flex flex-wrap justify-center gap-3">
              <Button onClick={() => navigate(`/student/petitions/${accepted.run_id}`)} className="bg-brand text-white">
                Track This Petition
                <ArrowRight className="size-4 ml-1.5" />
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setAccepted(null);
                  setFiles([]);
                  setTouched(false);
                  setF((p) => ({ ...p, petition_text: "", classes_attended: "", classes_held: "" }));
                }}
              >
                Submit Another Request
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  const isAttendance = f.petition_type === "attendance";

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Student Portal"
        title="Submit Academic Petition"
        description="Provide course details, attendance shortage metrics, and reason for consideration."
      />

      <form onSubmit={onSubmit} noValidate className="space-y-6">
        {/* Step 1: Category */}
        <Card className="shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-bold flex items-center gap-2">
              <span className="size-6 rounded-full bg-brand text-white flex items-center justify-center text-xs">1</span>
              Select Petition Category
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div role="radiogroup" aria-label="Petition category" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {TYPES.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  role="radio"
                  aria-checked={f.petition_type === t.id}
                  onClick={() => set("petition_type", t.id)}
                  className={`rounded-xl border p-3.5 text-left transition-all hover:bg-muted/60 ${
                    f.petition_type === t.id
                      ? "border-brand bg-brand/5 ring-2 ring-brand/30 shadow-sm"
                      : "border-border"
                  }`}
                >
                  <span className="flex items-center justify-between gap-2 text-sm font-semibold">
                    {t.label}
                    {!t.supported && <Badge variant="secondary" className="text-[10px]">Escalates</Badge>}
                  </span>
                  <span className="mt-1 block text-xs text-muted-foreground leading-relaxed">{t.blurb}</span>
                </button>
              ))}
            </div>
            {!isAttendance && (
              <Callout tone="warning" className="mt-3" title="Not yet supported">
                Only attendance petitions are analysed. This type will be passed straight to a human examiner without an AI recommendation.
              </Callout>
            )}
          </CardContent>
        </Card>

        {/* Step 2: Academic Details */}
        <Card className="shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-bold flex items-center gap-2">
              <span className="size-6 rounded-full bg-brand text-white flex items-center justify-center text-xs">2</span>
              Student & Course Information
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Field id="student_ref" label="Student reference" required hint="e.g. STU2026001 or SYN-000123" error={err("student_ref")}>
              <Input
                id="student_ref"
                value={f.student_ref}
                onChange={(e) => set("student_ref", e.target.value.toUpperCase())}
                aria-invalid={!!err("student_ref")}
                className="font-mono"
              />
            </Field>

            <Field id="program" label="Programme" required error={err("program")}>
              <Input
                id="program"
                value={f.program}
                onChange={(e) => set("program", e.target.value)}
                placeholder="Computer Science and Engineering"
                aria-invalid={!!err("program")}
              />
            </Field>

            <Field id="admission_batch" label="Admission batch" required hint="Format: 2025-26" error={err("admission_batch")}>
              <Input
                id="admission_batch"
                value={f.admission_batch}
                onChange={(e) => set("admission_batch", e.target.value)}
                aria-invalid={!!err("admission_batch")}
              />
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field id="course_code" label="Course code" required error={err("course_code")}>
                <Input
                  id="course_code"
                  value={f.course_code}
                  onChange={(e) => set("course_code", e.target.value.toUpperCase())}
                  placeholder="CS101"
                  aria-invalid={!!err("course_code")}
                />
              </Field>
              <Field id="semester" label="Semester" required error={err("semester")}>
                <Input
                  id="semester"
                  type="number"
                  min={1}
                  max={8}
                  value={f.semester}
                  onChange={(e) => set("semester", e.target.value)}
                  aria-invalid={!!err("semester")}
                />
              </Field>
            </div>
          </CardContent>
        </Card>

        {/* Step 3: Attendance Metrics */}
        {isAttendance && (
          <Card className="shadow-sm">
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-bold flex items-center gap-2">
                <span className="size-6 rounded-full bg-brand text-white flex items-center justify-center text-xs">3</span>
                Attendance Metrics & Grounds
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-3">
              <Field id="classes_held" label="Classes held" required error={err("classes_held")}>
                <Input
                  id="classes_held"
                  type="number"
                  min={1}
                  value={f.classes_held}
                  onChange={(e) => set("classes_held", e.target.value)}
                  aria-invalid={!!err("classes_held")}
                />
              </Field>

              <Field id="classes_attended" label="Classes attended" required error={err("classes_attended")}>
                <Input
                  id="classes_attended"
                  type="number"
                  min={0}
                  value={f.classes_attended}
                  onChange={(e) => set("classes_attended", e.target.value)}
                  aria-invalid={!!err("classes_attended")}
                />
              </Field>

              <div className="space-y-1.5">
                <p className="text-sm font-semibold leading-none">Calculated Percentage</p>
                <div className="flex h-10 items-center rounded-md bg-muted px-3 font-mono font-bold text-sm tabular-nums" aria-live="polite">
                  {pct === null ? "—" : `${pct}%`}
                </div>
                <p className="text-[11px] text-muted-foreground">Computed automatically</p>
              </div>

              <Field id="reason" label="Shortage Reason" required>
                <Select
                  id="reason"
                  value={f.reason_category}
                  onChange={(e) => set("reason_category", e.target.value as FormState["reason_category"])}
                >
                  <option value="medical">Medical emergency / Illness</option>
                  <option value="personal">Personal / Family grounds</option>
                  <option value="sports-cultural">University Sports / Cultural Representation</option>
                  <option value="other">Other exceptional circumstance</option>
                </Select>
              </Field>

              <Field id="doc" label="Documentation available" hint="Verified during examiner review" required>
                <Select
                  id="doc"
                  value={f.medical_documentation}
                  onChange={(e) => set("medical_documentation", e.target.value as FormState["medical_documentation"])}
                >
                  <option value="certificate">Registered Medical Certificate</option>
                  <option value="hospital-record">Official Hospitalization Record</option>
                  <option value="none">No official documentation</option>
                </Select>
              </Field>
            </CardContent>
          </Card>
        )}

        {/* Step 4: Statement & Documents */}
        <Card className="shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-bold flex items-center gap-2">
              <span className="size-6 rounded-full bg-brand text-white flex items-center justify-center text-xs">
                {isAttendance ? "4" : "3"}
              </span>
              Detailed Statement & Supporting Files
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Field
              id="petition_text"
              label="Describe your situation"
              required
              error={err("petition_text")}
              hint="Between 20 and 2000 characters. State dates, medical context, and classes missed."
            >
              <Textarea
                id="petition_text"
                rows={5}
                value={f.petition_text}
                onChange={(e) => set("petition_text", e.target.value)}
                aria-invalid={!!err("petition_text")}
                maxLength={2000}
                placeholder="State your reasons and relevant circumstances in detail…"
              />
            </Field>

            <p className="text-right text-xs tabular-nums text-muted-foreground">
              {f.petition_text.trim().length} / 2000 characters
            </p>

            <div className="rounded-xl border border-dashed p-4 bg-muted/20">
              <Field
                id="files"
                label="Supporting documents (optional)"
                hint="Accepted formats: PDF, PNG, JPEG · Max 2 MB per file · Up to 3 attachments."
              >
                <input
                  id="files"
                  type="file"
                  multiple
                  accept=".pdf,.png,.jpg,.jpeg"
                  className="block w-full text-sm file:mr-3 file:rounded-md file:border file:bg-card file:px-3 file:py-1.5 file:text-xs file:font-semibold hover:file:bg-muted"
                  onChange={(e) => {
                    const chosen = Array.from(e.target.files ?? []);
                    const ok = chosen.filter((x) => x.size <= 2 * 1024 * 1024);
                    if (ok.length < chosen.length) toast.error("Files larger than 2 MB were excluded");
                    if (ok.length > 3) toast.error("Maximum 3 documents allowed");
                    setFiles(ok.slice(0, 3));
                  }}
                />
              </Field>
              {files.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {files.map((x) => (
                    <Badge key={x.name} variant="outline" className="text-xs py-1">
                      📄 {x.name} ({(x.size / 1024).toFixed(0)} KB)
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        <div className="flex flex-wrap items-center justify-between gap-4 pt-2">
          <Button type="submit" size="lg" loading={submit.isPending} className="bg-brand text-white font-semibold">
            Submit Petition
          </Button>
          <span className="text-xs text-muted-foreground flex items-center gap-1.5">
            <Info className="size-4 text-brand" />
            Your petition will be reviewed under University Examination Bye-Laws.
          </span>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------- Student Detail View
export function StudentPetitionDetail() {
  const { id } = useParams();
  const q = useRun(id);
  useDocumentTitle(id ? `Petition ${id}` : "Petition Details");
  const [rating, setRating] = useState(5);

  const fb = useMutation({
    mutationFn: () => api.feedback(id!, { rating }),
    onSuccess: () => toast.success("Thank you for your feedback!"),
    onError: (e) => toast.error(e instanceof Error ? e.message : "Feedback failed"),
  });

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
  const last = run.examiner_decisions[run.examiner_decisions.length - 1];
  const p = run.petition;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Student Portal"
        title={`${titleCase(run.petition_type)} Petition`}
        description={`Tracking ID: ${run.run_id}`}
        actions={
          <Button asChild variant="outline" size="sm">
            <Link to="/student/petitions">Back to My Petitions</Link>
          </Button>
        }
      />

      {/* Status Bar */}
      <div className="flex flex-wrap items-center gap-3 p-4 rounded-xl border bg-card shadow-sm">
        <StatusBadge status={run.status} />
        <div className="h-4 w-px bg-border hidden sm:block" />
        <PipelineStepper run={run} />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Main Recommendation Column */}
        <div className="space-y-6 lg:col-span-2">
          <RecommendationPanel run={run} audience="student" />

          {/* Official Human Examiner Decision Section */}
          <section aria-labelledby="examinerDecisionHeading">
            <h2 id="examinerDecisionHeading" className="text-sm font-bold text-foreground mb-3 flex items-center gap-2">
              <UserCheck className="size-4 text-brand" />
              Official Examination Board Ruling
            </h2>
            {last ? (
              <div className="space-y-4">
                <Callout
                  tone={last.decision === "accept-petition" ? "success" : last.decision === "reject-petition" ? "danger" : "warning"}
                  title={`${last.decision === "accept-petition" ? "Petition Accepted" : last.decision === "reject-petition" ? "Petition Rejected" : "Additional Information Requested"} · ${formatDateTime(last.ts)}`}
                >
                  <p className="font-medium text-foreground">Attributed Examiner: {last.examiner_label}</p>
                  <p className="mt-1.5 leading-relaxed"><strong>Ruling Note:</strong> {last.note}</p>
                </Callout>
                {last.decision === "request-more-information" && (
                  <div className="p-4 rounded-xl border border-amber-300 dark:border-amber-800 bg-amber-500/10 space-y-3">
                    <p className="text-xs font-semibold text-amber-900 dark:text-amber-200">
                      The board requires additional verification documents to process your condonation. Please attach relevant certificates below:
                    </p>
                    <DocumentUploader runId={run.run_id} existing={run.documents.length} />
                  </div>
                )}
              </div>
            ) : (
              <Callout tone="info" title="Pending Human Examiner Determination">
                The AI triage assessment is complete. An appointed examination officer will evaluate the evidence and record the binding university decision. You will receive an update here.
              </Callout>
            )}
          </section>
        </div>

        {/* Sidebar Info Column */}
        <div className="space-y-5">
          {p && (
            <Card className="shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-bold">Your Petition Record</CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-xs">
                  {[
                    ["Student ID", p.student_ref],
                    ["Course Code", `${p.course_code} (Sem ${p.semester})`],
                    ["Programme", p.program],
                    ["Attendance %", p.attendance_percentage != null ? `${p.attendance_percentage}%` : "—"],
                    ["Reason", titleCase(p.reason_category)],
                    ["Documentation", titleCase(p.medical_documentation)],
                  ].map(([k, v]) => (
                    <Fragment key={k}>
                      <dt className="text-muted-foreground">{k}</dt>
                      <dd className="font-semibold text-foreground">{v}</dd>
                    </Fragment>
                  ))}
                </dl>
                <div className="mt-3.5 border-t pt-3">
                  <p className="text-[11px] font-medium text-muted-foreground mb-1">Statement:</p>
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
                <span>Supporting Files</span>
                <Badge variant="outline" className="text-[10px]">{run.documents.length} attached</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <DocumentList runId={run.run_id} documents={run.documents} />
              <DocumentUploader runId={run.run_id} existing={run.documents.length} />
            </CardContent>
          </Card>

          {/* Feedback */}
          {(run.status === "completed" || run.status === "escalated") && (
            <Card className="shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-bold">Feedback on Analysis</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <Field id="rating" label={`Quality Rating: ${rating} / 5`}>
                  <input
                    id="rating"
                    type="range"
                    min={1}
                    max={5}
                    value={rating}
                    onChange={(e) => setRating(Number(e.target.value))}
                    className="w-full accent-brand cursor-pointer"
                  />
                </Field>
                <Button variant="outline" size="sm" loading={fb.isPending} onClick={() => fb.mutate()} className="w-full">
                  Submit Feedback
                </Button>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Student Profile Page
export function StudentProfile() {
  useDocumentTitle("Student Profile");
  const { user } = useAuth();
  const studentRef = user?.user_id || "STU2026001";
  const q = useMyRuns(studentRef);

  const runs = q.data?.runs ?? [];
  const pendingHuman = runs.filter((r) => !r.examiner_decision).length;
  const approved = runs.filter((r) => r.examiner_decision === "accept-petition").length;
  const escalated = runs.filter((r) => r.status === "escalated" || r.examiner_decision === "request-more-information").length;

  const initials = (user?.name || "Student")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Student Portal"
        title="Student Profile & Academic Dossier"
        description="Verified student enrollment record, authentication scope, and petition summary."
        actions={
          <div className="flex items-center gap-2">
            <Button asChild variant="outline" size="sm">
              <Link to="/student/petitions">Petition History</Link>
            </Button>
            <Button asChild size="sm" className="bg-brand text-white">
              <Link to="/student/new">
                <FilePlus2 className="size-4" />
                New Petition
              </Link>
            </Button>
          </div>
        }
      />

      {/* Main Student Identification Banner */}
      <Card className="border shadow-sm overflow-hidden bg-card">
        <div className="h-1.5 w-full bg-gradient-to-r from-[#C66A32] via-[#E69A45] to-[#C66A32]" />
        <CardContent className="p-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
            <div className="flex items-start sm:items-center gap-4">
              <div className="size-16 sm:size-20 rounded-2xl bg-gradient-to-tr from-[#C66A32] to-[#E69A45] text-white flex items-center justify-center text-xl sm:text-2xl font-black shadow-md border-2 border-white dark:border-slate-800 shrink-0">
                {initials}
              </div>
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-xl sm:text-2xl font-black tracking-tight text-foreground">
                    {user?.name || "Alex Mercer"}
                  </h2>
                  <Badge variant="outline" className="text-xs bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/30">
                    <UserCheck className="size-3 mr-1" /> Active Enrolled
                  </Badge>
                </div>
                <p className="text-xs sm:text-sm text-muted-foreground flex flex-wrap items-center gap-2">
                  <span className="font-mono font-semibold text-foreground">{user?.user_id}</span>
                  {user?.usn && (
                    <>
                      <span>•</span>
                      <span>USN: <strong className="font-mono text-foreground">{user.usn}</strong></span>
                    </>
                  )}
                  <span>•</span>
                  <span>{user?.email || `${user?.user_id?.toLowerCase()}@apex.edu`}</span>
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="rounded-xl border bg-muted/40 p-3 text-right text-xs">
                <p className="text-muted-foreground font-medium">Record Privacy Status</p>
                <p className="font-bold text-emerald-600 dark:text-emerald-400 flex items-center justify-end gap-1 mt-0.5">
                  <Shield className="size-3.5" /> Isolated Student Scope
                </p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 2-Column Detail Cards */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Academic Program Information */}
        <Card className="shadow-sm">
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm font-bold flex items-center gap-2">
              <GraduationCap className="size-4 text-brand" />
              Academic Enrollment Details
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-4 space-y-3.5 text-xs">
            <div className="flex items-center justify-between py-1 border-b border-border/50">
              <span className="text-muted-foreground flex items-center gap-1.5">
                <Building2 className="size-3.5" /> Department / Branch
              </span>
              <span className="font-semibold text-foreground">{user?.branch || "Computer Science and Engineering"}</span>
            </div>
            <div className="flex items-center justify-between py-1 border-b border-border/50">
              <span className="text-muted-foreground flex items-center gap-1.5">
                <BookOpen className="size-3.5" /> Current Semester & Section
              </span>
              <span className="font-semibold text-foreground">
                Semester {user?.semester ?? 6} · Section {user?.section ?? "A"}
              </span>
            </div>
            <div className="flex items-center justify-between py-1 border-b border-border/50">
              <span className="text-muted-foreground flex items-center gap-1.5">
                <Calendar className="size-3.5" /> Academic Year / Batch
              </span>
              <span className="font-semibold text-foreground">2025–26 (Admission 2023)</span>
            </div>
            <div className="flex items-center justify-between py-1 border-b border-border/50">
              <span className="text-muted-foreground flex items-center gap-1.5">
                <Mail className="size-3.5" /> Institutional Email
              </span>
              <span className="font-mono text-foreground">{user?.email || `${user?.user_id?.toLowerCase()}@apex.edu`}</span>
            </div>
            <div className="flex items-center justify-between py-1">
              <span className="text-muted-foreground flex items-center gap-1.5">
                <User className="size-3.5" /> Student Reference (USN)
              </span>
              <span className="font-mono font-bold text-foreground">{user?.usn || "SYN-202601"}</span>
            </div>
          </CardContent>
        </Card>

        {/* Security & Access Authorization */}
        <Card className="shadow-sm">
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm font-bold flex items-center gap-2">
              <Shield className="size-4 text-brand" />
              Security & Role Authorization
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-4 space-y-3.5 text-xs">
            <div className="flex items-center justify-between py-1 border-b border-border/50">
              <span className="text-muted-foreground">Portal Role</span>
              <Badge variant="outline" className="font-semibold capitalize text-brand bg-brand/10 border-brand/20">
                {user?.role || "student"}
              </Badge>
            </div>
            <div className="flex items-center justify-between py-1 border-b border-border/50">
              <span className="text-muted-foreground">Password Hash</span>
              <span className="font-mono text-muted-foreground">Bcrypt (cost 12)</span>
            </div>
            <div className="flex items-center justify-between py-1 border-b border-border/50">
              <span className="text-muted-foreground">Access Scope</span>
              <span className="font-semibold text-foreground">Self-Only (Strict Student Isolation)</span>
            </div>
            <div className="flex items-center justify-between py-1 border-b border-border/50">
              <span className="text-muted-foreground">Examiner Decision Access</span>
              <span className="text-muted-foreground">Read-Only (Upon Publication)</span>
            </div>
            <div className="flex items-center justify-between py-1">
              <span className="text-muted-foreground">Authentication Protocol</span>
              <span className="font-semibold text-emerald-600 dark:text-emerald-400">Bearer Session Token</span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Petition Statistics Grid */}
      <div>
        <h3 className="text-sm font-bold text-foreground mb-3">Petition Activity Overview</h3>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            label="Total Submitted"
            value={q.isLoading ? "…" : runs.length}
            hint="Cases on academic record"
          />
          <StatCard
            label="Awaiting Board"
            value={q.isLoading ? "…" : pendingHuman}
            tone={pendingHuman > 0 ? "warning" : undefined}
            hint="In review queue"
          />
          <StatCard
            label="Condonation Approved"
            value={q.isLoading ? "…" : approved}
            tone="success"
            hint="Official approval"
          />
          <StatCard
            label="Committee Escalations"
            value={q.isLoading ? "…" : escalated}
            hint="Special board consideration"
          />
        </div>
      </div>

      {/* Recent Submissions */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-foreground">Recent Submissions for {user?.name}</h3>
          <Button asChild variant="ghost" size="sm" className="text-xs">
            <Link to="/student/petitions">View Full List ({runs.length})</Link>
          </Button>
        </div>
        {q.isLoading ? (
          <Skeleton className="h-40 rounded-xl" />
        ) : runs.length === 0 ? (
          <EmptyState
            icon={<FilePlus2 />}
            title="No petitions on file"
            action={
              <Button asChild className="bg-brand text-white">
                <Link to="/student/new">Submit a Petition</Link>
              </Button>
            }
          >
            No petition submissions found for {studentRef}.
          </EmptyState>
        ) : (
          <PetitionRows runs={runs.slice(0, 3)} />
        )}
      </div>
    </div>
  );
}
