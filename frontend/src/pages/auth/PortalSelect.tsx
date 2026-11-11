import { useQuery } from "@tanstack/react-query";
import { Activity, ArrowRight, CheckCircle2, ChevronRight, GraduationCap, ShieldCheck, Sparkles } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/authContext";

export function PortalSelect() {
  const navigate = useNavigate();
  const { isAuthenticated, role, user, logout } = useAuth();
  const healthQ = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: import.meta.env.MODE === "test" ? false : 30000,
    retry: false,
  });
  const demoQ = useQuery({ queryKey: ["demo-creds"], queryFn: api.demoCredentials, retry: false });

  const checks = healthQ.data?.checks;
  const isHealthy = healthQ.data?.status === "ready";

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">
      {/* Top Navigation */}
      <header className="border-b bg-card/90 backdrop-blur sticky top-0 z-30 px-6 py-3.5 flex items-center justify-between shadow-xs">
        <div className="flex items-center gap-3">
          <div className="size-9 rounded-xl bg-brand text-white flex items-center justify-center shadow-sm">
            <ShieldCheck className="size-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-base tracking-tight text-foreground">Apex University</span>
              <Badge variant="outline" className="text-[10px] uppercase font-semibold tracking-wider border-brand/30 text-brand bg-brand/5">Academic Affairs</Badge>
            </div>
            <p className="text-xs text-muted-foreground">Autonomous Petition Triage & Regulatory Verification System</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="hidden sm:flex items-center gap-2 text-xs px-2.5 py-1 rounded-full border bg-muted/40">
            <span className={`size-2 rounded-full ${isHealthy ? "bg-emerald-600 animate-pulse" : "bg-amber-600"}`} />
            <span className="text-muted-foreground">Engine:</span>
            <span className="font-medium text-foreground">{healthQ.isLoading ? "Connecting…" : isHealthy ? "Online & Ready" : "Degraded"}</span>
          </div>

          {isAuthenticated && user ? (
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigate(role === "examiner" ? "/examiner/dashboard" : "/student/dashboard")}
                className="text-xs gap-1.5"
              >
                Go to {role === "examiner" ? "Examiner" : "Student"} Dashboard
                <ArrowRight className="size-3.5" />
              </Button>
              <Button variant="ghost" size="sm" onClick={() => logout()} className="text-xs text-muted-foreground">
                Sign Out
              </Button>
            </div>
          ) : (
            <span className="text-xs text-muted-foreground hidden md:inline">Select your destination portal below</span>
          )}
        </div>
      </header>

      {/* Hero Section */}
      <main className="flex-1 max-w-6xl w-full mx-auto px-6 py-12 flex flex-col justify-center">
        <div className="text-center max-w-2xl mx-auto mb-10 space-y-3">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-brand/10 text-brand border border-brand/20">
            <Sparkles className="size-3.5" />
            Triple-Agent LangGraph RAG + Verbatim Policy Verification
          </div>
          <h1 className="text-3xl md:text-4xl font-extrabold tracking-tight text-foreground">
            Academic Petition Triage Portal
          </h1>
          <p className="text-sm md:text-base text-muted-foreground leading-relaxed">
            Welcome to the centralized university academic petition gateway. Students submit attendance shortage and exceptional requests; AI agents verify regulatory clauses against university statutes; certified human examiners make all binding decisions.
          </p>
        </div>

        {/* Portals Selection Grid */}
        <div className="grid md:grid-cols-2 gap-6 max-w-4xl mx-auto w-full">
          {/* Student Portal Card */}
          <Card className="relative overflow-hidden border hover:border-brand/60 transition-all duration-300 shadow-sm hover:shadow-md group flex flex-col justify-between bg-card">
            <div className="absolute top-0 left-0 right-0 h-1.5 bg-gradient-to-r from-brand via-amber-500 to-brand" />
            <CardHeader className="pt-7 pb-4">
              <div className="size-12 rounded-xl bg-brand/10 text-brand flex items-center justify-center mb-4 group-hover:scale-105 transition-transform duration-200 shadow-xs border border-brand/20">
                <GraduationCap className="size-6" />
              </div>
              <div className="flex items-center justify-between">
                <CardTitle className="text-xl font-bold tracking-tight text-foreground">Student Portal</CardTitle>
                <Badge variant="secondary" className="text-xs font-medium">Undergraduate & Postgrad</Badge>
              </div>
              <CardDescription className="text-sm leading-relaxed mt-1.5">
                Submit academic shortage petitions, upload certified medical documentation, follow real-time AI triage progression, and track human examiner determinations.
              </CardDescription>
            </CardHeader>

            <CardContent className="space-y-3 text-xs text-muted-foreground pb-4">
              <div className="p-3 rounded-lg bg-muted/40 border space-y-2">
                <div className="flex items-center gap-2 text-foreground font-medium">
                  <CheckCircle2 className="size-3.5 text-emerald-600 dark:text-emerald-400" />
                  <span>Autonomous Clause & Regulation Verification</span>
                </div>
                <div className="flex items-center gap-2 text-foreground font-medium">
                  <CheckCircle2 className="size-3.5 text-emerald-600 dark:text-emerald-400" />
                  <span>Supporting Medical Evidence Attachment</span>
                </div>
                <div className="flex items-center gap-2 text-foreground font-medium">
                  <CheckCircle2 className="size-3.5 text-emerald-600 dark:text-emerald-400" />
                  <span>Isolated Student Privacy & Case Tracking</span>
                </div>
              </div>

              {demoQ.data?.enabled && (
                <div className="flex items-center justify-between px-3 py-2 rounded-md bg-brand/5 border border-brand/20 text-[11px]">
                  <span className="text-brand font-semibold">Demo Account:</span>
                  <span className="font-mono text-foreground font-medium">STU2026001 / Student@123</span>
                </div>
              )}
            </CardContent>

            <CardFooter className="pt-2 pb-6">
              <Button asChild className="w-full bg-brand hover:bg-brand/90 text-white font-medium py-2.5 shadow-xs group-hover:shadow transition-all gap-2">
                <Link to="/student/login">
                  Enter Student Portal
                  <ChevronRight className="size-4 group-hover:translate-x-0.5 transition-transform" />
                </Link>
              </Button>
            </CardFooter>
          </Card>

          {/* Examiner Portal Card */}
          <Card className="relative overflow-hidden border hover:border-foreground/40 transition-all duration-300 shadow-sm hover:shadow-md group flex flex-col justify-between bg-card">
            <div className="absolute top-0 left-0 right-0 h-1.5 bg-gradient-to-r from-foreground via-muted-foreground to-foreground" />
            <CardHeader className="pt-7 pb-4">
              <div className="size-12 rounded-xl bg-foreground/10 text-foreground flex items-center justify-center mb-4 group-hover:scale-105 transition-transform duration-200 shadow-xs border border-foreground/20">
                <ShieldCheck className="size-6" />
              </div>
              <div className="flex items-center justify-between">
                <CardTitle className="text-xl font-bold tracking-tight text-foreground">Examiner Portal</CardTitle>
                <Badge variant="outline" className="text-xs font-medium border-amber-600/30 bg-amber-500/10 text-amber-700 dark:text-amber-400">Official Board Only</Badge>
              </div>
              <CardDescription className="text-sm leading-relaxed mt-1.5">
                Review prioritized petition queues, inspect AI-extracted verbatim evidence, check open interpretation questions, request supplemental info, and record final rulings.
              </CardDescription>
            </CardHeader>

            <CardContent className="space-y-3 text-xs text-muted-foreground pb-4">
              <div className="p-3 rounded-lg bg-muted/40 border space-y-2">
                <div className="flex items-center gap-2 text-foreground font-medium">
                  <CheckCircle2 className="size-3.5 text-emerald-600 dark:text-emerald-400" />
                  <span>Executive Review Queue & Priority Triage</span>
                </div>
                <div className="flex items-center gap-2 text-foreground font-medium">
                  <CheckCircle2 className="size-3.5 text-emerald-600 dark:text-emerald-400" />
                  <span>Attributed & Immutable Human Decisions</span>
                </div>
                <div className="flex items-center gap-2 text-foreground font-medium">
                  <CheckCircle2 className="size-3.5 text-emerald-600 dark:text-emerald-400" />
                  <span>Comprehensive Agent & Retrieval Observability</span>
                </div>
              </div>

              {demoQ.data?.enabled && (
                <div className="flex items-center justify-between px-3 py-2 rounded-md bg-muted/60 border text-[11px]">
                  <span className="text-foreground font-semibold">Demo Account:</span>
                  <span className="font-mono text-foreground font-medium">EXM2026001 / Examiner@123</span>
                </div>
              )}
            </CardContent>

            <CardFooter className="pt-2 pb-6">
              <Button asChild className="w-full bg-foreground hover:bg-foreground/90 text-background font-medium py-2.5 shadow-xs group-hover:shadow transition-all gap-2">
                <Link to="/examiner/login">
                  Enter Examiner Portal
                  <ChevronRight className="size-4 group-hover:translate-x-0.5 transition-transform" />
                </Link>
              </Button>
            </CardFooter>
          </Card>
        </div>

        {/* Live System Specs Bar */}
        <div className="mt-12 max-w-4xl mx-auto w-full p-4 rounded-xl border bg-card/60 backdrop-blur shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-4 text-xs">
            <div className="flex items-center gap-2">
              <Activity className="size-4 text-brand" />
              <span className="font-semibold text-foreground">Live Infrastructure Status</span>
            </div>
            <div className="flex flex-wrap items-center gap-4 text-muted-foreground">
              <span>FastAPI Backend: <strong className="text-foreground">{checks?.database === "ok" ? "Connected" : "Standby"}</strong></span>
              <span>•</span>
              <span>ChromaDB Vector: <strong className="text-foreground">{checks?.chroma === "ok" ? "Available" : "Not Set"}</strong></span>
              <span>•</span>
              <span>RQ Workers: <strong className="text-foreground">{checks?.workers ?? "0"} Active</strong></span>
              <span>•</span>
              <span>Model Mode: <strong className="text-foreground">{checks?.llm === "configured" ? "Live Provider" : "Local / Stub"}</strong></span>
            </div>
          </div>
        </div>

        {/* Governance Disclaimer */}
        <p className="mt-8 text-center text-xs text-muted-foreground max-w-2xl mx-auto leading-relaxed">
          <strong>Academic Governance Policy:</strong> The AI system performs semantic & BM25 regulation retrieval and candidate assessment only. The system does not possess deciding authority; every academic petition requires a signed determination by a designated University Examination Officer.
        </p>
      </main>

      <footer className="border-t py-4 text-center text-xs text-muted-foreground">
        © 2026 Apex University Academic Affairs & Examination Division. All rights reserved.
      </footer>
    </div>
  );
}
