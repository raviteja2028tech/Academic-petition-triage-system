import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RecommendationPanel, PipelineStepper } from "@/components/petition/shared";
import { ApiError, api } from "@/lib/api";
import { AuthProvider } from "@/lib/authContext";
import type { RunView } from "@/lib/types";
import { formatBytes, isTerminal, titleCase } from "@/lib/utils";
import { ExaminerLogin } from "@/pages/auth/ExaminerLogin";
import { PortalSelect } from "@/pages/auth/PortalSelect";
import { StudentLogin } from "@/pages/auth/StudentLogin";
import { NewPetition } from "@/pages/student/StudentPages";

// A structurally valid API payload used only as test INPUT for rendering logic (the app itself never ships mock data).
const run = (over: Partial<RunView> = {}): RunView => ({
  run_id: "run_test", status: "escalated", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:10Z",
  petition_type: "attendance", student_ref: "SYN-000001", mode: "agents", error: null, petition: null,
  examiner_decisions: [], documents: [],
  events: [
    { ts: "t", event: "agent_start", detail: { agent: "triage" } }, { ts: "t", event: "agent_end", detail: { agent: "triage", ok: true } },
    { ts: "t", event: "agent_start", detail: { agent: "research" } }, { ts: "t", event: "agent_end", detail: { agent: "research", ok: true } },
    { ts: "t", event: "agent_start", detail: { agent: "verifier" } }, { ts: "t", event: "agent_end", detail: { agent: "verifier", ok: true } },
  ],
  result: {
    mode: "agents", route: "refer-to-committee", position: "Below the minimum.", basis: "See clauses.", disclaimer: "x", message: "m",
    escalation: { required: true, reason: "committee_discretion", detail: "VC decides." },
    citations: [{ evidence_id: "E1", chunk_id: "c", document: "doc.pdf", chapter: "25OB10.0 Attendance", clause_id: "25OB10.0(5)", page: 19, quote: "may be condoned by the Vice-Chancellor", verified: true }],
    open_questions: [{ id: "OQ1", topic: "meaning of '10 %'", text: "Unconfirmed reading." }],
    human_review_checklist: ["Check the certificate."], llm_models: ["real-model"],
    triage: { confidence: 0.9, summary: "s", flags: [], classified_type: "attendance", declared_type: "attendance", attendance_percentage: 80, medical_grounds_claimed: true, documentation: "certificate", supported: true },
  },
  ...over,
});

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>
);

const wrapWithAuth = (ui: React.ReactElement, initialEntries = ["/"]) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <AuthProvider>
      <MemoryRouter initialEntries={initialEntries}>
        {ui}
      </MemoryRouter>
    </AuthProvider>
  </QueryClientProvider>
);

describe("utils", () => {
  it("formats values", () => {
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(titleCase("committee_discretion")).toBe("Committee Discretion");
    expect(isTerminal("escalated")).toBe(true);
    expect(isTerminal("running")).toBe(false);
  });
});

describe("RecommendationPanel", () => {
  it("shows verified citations, the escalation, uncertainty and that a human must decide", () => {
    render(wrap(<RecommendationPanel run={run()} audience="examiner" />));
    expect(screen.getByText(/not a decision/i)).toBeInTheDocument();
    expect(screen.getByText("25OB10.0(5)")).toBeInTheDocument();
    expect(screen.getByText(/Quote found in source/)).toBeInTheDocument();
    expect(screen.getByText(/Escalated for human decision/)).toBeInTheDocument();
    expect(screen.getByText(/A human examiner must review this petition/)).toBeInTheDocument();
    expect(screen.getByText(/Unresolved interpretations \(1\)/)).toBeInTheDocument();
    expect(screen.getByText("90%")).toBeInTheDocument();                       // triage confidence (examiner only)
    expect(screen.getByText(/Reviewer checklist/)).toBeInTheDocument();
  });
  it("hides examiner-only details from the student", () => {
    render(wrap(<RecommendationPanel run={run()} audience="student" />));
    expect(screen.queryByText(/Reviewer checklist/)).toBeNull();
    expect(screen.queryByText("90%")).toBeNull();
    expect(screen.getByText(/Nothing on this page is a university decision/)).toBeInTheDocument();
  });
  it("warns when the answer came from a stub model", () => {
    const r = run(); r.result!.llm_models = ["stub-model"];
    render(wrap(<RecommendationPanel run={r} audience="examiner" />));
    expect(screen.getByText(/stub \/ scripted model/i)).toBeInTheDocument();
  });
  it("shows a safe message when there was no determination", () => {
    const r = run(); r.result!.position = "NO_DETERMINATION"; r.result!.citations = [];
    render(wrap(<RecommendationPanel run={r} audience="student" />));
    expect(screen.getByText(/did not make a determination/i)).toBeInTheDocument();
    expect(screen.getByText(/No citation was verified/)).toBeInTheDocument();
  });
  it("shows a running state and a failure state", () => {
    const { rerender } = render(wrap(<RecommendationPanel run={run({ status: "running", result: null })} audience="student" />));
    expect(screen.getByText(/AI is analysing/)).toBeInTheDocument();
    rerender(wrap(<RecommendationPanel run={run({ status: "failed", result: null, error: "boom" })} audience="student" />));
    expect(screen.getByText(/analysis failed/i)).toBeInTheDocument();
  });
});

describe("PipelineStepper", () => {
  it("marks agents as done and skipped agents when the run ended early", () => {
    const r = run({ events: [{ ts: "t", event: "agent_start", detail: { agent: "triage" } }, { ts: "t", event: "agent_end", detail: { agent: "triage", ok: true } }] });
    render(wrap(<PipelineStepper run={r} />));
    expect(screen.getAllByText(/skipped/).length).toBe(2);
  });
});

describe("api client", () => {
  afterEach(() => vi.restoreAllMocks());
  it("maps a 422 to field errors", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ errors: [{ field: "semester", rule: "x", message: "bad" }] }), { status: 422 }));
    await expect(api.submit({} as never)).rejects.toMatchObject({ status: 422, fieldErrors: [{ field: "semester", message: "bad" }] });
  });
  it("reports an unreachable backend clearly", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("down"));
    await expect(api.runs()).rejects.toBeInstanceOf(ApiError);
    await expect(api.runs()).rejects.toThrow(/unreachable/);
  });
  it("surfaces rate limiting", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Rate limit exceeded", retry_after_seconds: 7 }), { status: 429 }));
    await expect(api.submit({} as never)).rejects.toMatchObject({ status: 429, retryAfter: 7 });
  });
});

describe("NewPetition form", () => {
  beforeEach(() => localStorage.clear());
  it("blocks submission, shows inline errors and never calls the API when the form is invalid", async () => {
    const spy = vi.spyOn(api, "submit");
    render(wrap(<NewPetition />));
    await userEvent.click(screen.getByRole("button", { name: /submit petition/i }));
    expect(await screen.findAllByRole("alert")).not.toHaveLength(0);
    expect(screen.getByText(/Use the format SYN-000123/)).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });
  it("calculates the attendance percentage and explains unsupported categories", async () => {
    render(wrap(<NewPetition />));
    await userEvent.type(screen.getByLabelText(/classes held/i), "50");
    await userEvent.type(screen.getByLabelText(/classes attended/i), "40");
    await waitFor(() => expect(screen.getByText("80%")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("radio", { name: /re-evaluation/i }));
    expect(screen.getByText(/Not yet supported/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/classes held/i)).toBeNull();
  });
  it("submits a valid petition and shows the confirmation", async () => {
    const spy = vi.spyOn(api, "submit").mockResolvedValue({ run_id: "run_abc", status: "queued" });
    render(wrap(<NewPetition />));
    const t = userEvent;
    await t.type(screen.getByLabelText(/^student reference/i), "SYN-000123");
    await t.type(screen.getByLabelText(/^programme/i), "Computer Science");
    await t.type(screen.getByLabelText(/course code/i), "CS101");
    await t.type(screen.getByLabelText(/classes held/i), "100");
    await t.type(screen.getByLabelText(/classes attended/i), "80");
    await t.type(screen.getByLabelText(/describe your situation/i), "I was hospitalised for three weeks.");
    await t.click(screen.getByRole("button", { name: /submit petition/i }));
    expect(await screen.findByText("run_abc")).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith(expect.objectContaining({ student_ref: "SYN-000123", attendance_percentage: 80, classes_held: 100 }));
  });
});

describe("Authentication Pages", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders portal selection page with student and examiner options", async () => {
    vi.spyOn(api, "health").mockResolvedValue({ status: "ready", checks: { database: "ok", chroma: "ok" } });
    vi.spyOn(api, "demoCredentials").mockResolvedValue({
      enabled: true,
      student: { id: "STU2026001", password: "Student@123", name: "Alex Mercer" },
      examiner: { id: "EXM2026001", password: "Examiner@123", name: "Dr. Eleanor Vance" },
    });

    render(wrapWithAuth(<PortalSelect />, ["/"]));

    expect(screen.getByText(/Academic Petition Triage Portal/i)).toBeInTheDocument();
    expect(screen.getByText("Student Portal")).toBeInTheDocument();
    expect(screen.getByText("Examiner Portal")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /enter student portal/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /enter examiner portal/i })).toBeInTheDocument();
  });

  it("renders student login and auto-fills demo credentials", async () => {
    render(wrapWithAuth(<StudentLogin />, ["/student/login"]));

    expect(screen.getByRole("heading", { name: /student portal login/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/student id/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();

    const fillButton = screen.getByRole("button", { name: /fill stu2026001/i });
    fireEvent.click(fillButton);

    expect(screen.getByLabelText(/student id/i)).toHaveValue("STU2026001");
    expect(screen.getByLabelText(/^password$/i)).toHaveValue("Student@123");
  });

  it("executes student login and stores token on success", async () => {
    const mockUser = { user_id: "STU2026001", role: "student" as const, name: "Alex Mercer" };
    const loginSpy = vi.spyOn(api, "studentLogin").mockResolvedValue({
      access_token: "mock_token_stu",
      token_type: "bearer",
      expires_in: 7200,
      user: mockUser,
    });

    const { container } = render(wrapWithAuth(<StudentLogin />, ["/student/login"]));

    fireEvent.change(screen.getByLabelText(/student id/i), { target: { value: "STU2026001" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "Student@123" } });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => {
      expect(loginSpy).toHaveBeenCalledWith({ user_id: "STU2026001", password: "Student@123" });
      expect(localStorage.getItem("academic_triage_auth_token")).toBe("mock_token_stu");
    });
  });

  it("renders examiner login and allows demo credentials fill", async () => {
    render(wrapWithAuth(<ExaminerLogin />, ["/examiner/login"]));

    expect(screen.getByRole("heading", { name: /examiner board portal/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/examiner id/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();

    const fillBtn = screen.getByRole("button", { name: /fill exm2026001/i });
    fireEvent.click(fillBtn);

    expect(screen.getByLabelText(/examiner id/i)).toHaveValue("EXM2026001");
    expect(screen.getByLabelText(/^password$/i)).toHaveValue("Examiner@123");
  });

  it("executes examiner login successfully", async () => {
    const mockUser = { user_id: "EXM2026001", role: "examiner" as const, name: "Dr. Eleanor Vance" };
    const loginSpy = vi.spyOn(api, "examinerLogin").mockResolvedValue({
      access_token: "mock_token_exm",
      token_type: "bearer",
      expires_in: 7200,
      user: mockUser,
    });

    const { container } = render(wrapWithAuth(<ExaminerLogin />, ["/examiner/login"]));

    fireEvent.change(screen.getByLabelText(/examiner id/i), { target: { value: "EXM2026001" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "Examiner@123" } });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => {
      expect(loginSpy).toHaveBeenCalledWith({ user_id: "EXM2026001", password: "Examiner@123" });
      expect(localStorage.getItem("academic_triage_auth_token")).toBe("mock_token_exm");
    });
  });
});
