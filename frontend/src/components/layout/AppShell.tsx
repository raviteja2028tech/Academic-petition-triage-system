import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
  FilePlus2,
  FileText,
  Inbox,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  ShieldCheck,
  Sun,
  User,
} from "lucide-react";
import { useEffect } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Sheet, SheetClose, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/authContext";
import { useTheme } from "@/lib/hooks";
import { cn } from "@/lib/utils";

export type Role = "student" | "examiner" | "monitor";

const STUDENT_NAV = [
  { to: "/student/dashboard", label: "Dashboard Overview", icon: <LayoutDashboard />, end: true },
  { to: "/student/new", label: "Submit New Petition", icon: <FilePlus2 /> },
  { to: "/student/petitions", label: "My Petitions History", icon: <FileText /> },
  { to: "/student/profile", label: "Student Profile", icon: <User /> },
];

const EXAMINER_NAV = [
  { to: "/examiner/dashboard", label: "Executive Dashboard", icon: <LayoutDashboard />, end: true },
  { to: "/examiner/queue", label: "Petition Review Queue", icon: <Inbox />, withBadge: true },
  { to: "/monitor", label: "System & Workers", icon: <Activity />, end: true },
  { to: "/monitor/evaluation", label: "AI Evaluation Report", icon: <BarChart3 /> },
];

function Brand() {
  return (
    <div className="flex items-center gap-3 px-1 py-1">
      <div className="grid size-9 place-items-center rounded-xl bg-[#C66A32] text-white shadow-md">
        <ShieldCheck className="size-5" aria-hidden />
      </div>
      <div className="leading-tight">
        <p className="text-sm font-bold tracking-tight text-[#F7F4EF]">Apex University</p>
        <p className="text-[11px] text-[#B4ADA5] font-medium">Academic Petition Triage</p>
      </div>
    </div>
  );
}

function ServiceStatus() {
  const q = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30000, retry: false });
  const c = q.data?.checks;
  const rows: [string, "ok" | "warn" | "bad", string][] = q.isError
    ? [["API", "bad", "unreachable"]]
    : q.isLoading
    ? []
    : [
        ["API", "ok", "online"],
        ["LLM", c?.llm === "configured" ? (c?.llm_breaker === "open" ? "bad" : "ok") : "warn", c?.llm === "configured" ? (c?.llm_breaker === "open" ? "breaker open" : "configured") : "not set"],
        ["Workers", c?.workers && c.workers !== "0" ? "ok" : "warn", c?.workers ?? "?"],
      ];
  const dot = { ok: "bg-[#32866A]", warn: "bg-[#D99A36]", bad: "bg-[#C65353]" } as const;

  return (
    <div className="rounded-xl border border-[#3D3A36] bg-[#1E1C1A] p-3 text-xs shadow-sm" aria-label="Service status">
      <div className="flex items-center justify-between pb-2 mb-2 border-b border-[#3D3A36] text-[11px] font-semibold text-[#B4ADA5]">
        <span>ENGINE STATUS</span>
        <span className="flex items-center gap-1 text-[#32866A] font-medium">
          <span className="size-1.5 rounded-full bg-[#32866A] animate-pulse" /> Live
        </span>
      </div>
      {rows.length === 0 && <p className="text-[#8E867E] text-center py-1">Checking services…</p>}
      {rows.map(([k, s, v]) => (
        <div key={k} className="flex items-center justify-between py-1">
          <span className="text-[#B4ADA5]">{k}</span>
          <span className="flex items-center gap-1.5 font-medium text-[#F7F4EF]">
            <span className={cn("size-2 rounded-full", dot[s])} aria-hidden />
            {v}
          </span>
        </div>
      ))}
    </div>
  );
}

function SidebarBody({ role, onNavigate }: { role: "student" | "examiner"; onNavigate?: () => void }) {
  const pendingCountQ = useQuery({
    queryKey: ["runs", "pending-count"],
    queryFn: () => api.runs({ limit: 1, awaiting_decision: true }),
    enabled: role === "examiner",
    refetchInterval: 15000,
  });

  const pendingCount = pendingCountQ.data?.matched ?? 0;
  const navItems = role === "examiner" ? EXAMINER_NAV : STUDENT_NAV;

  return (
    <div className="flex h-full flex-col gap-5 p-4 bg-[#292725] text-[#F7F4EF]">
      <Brand />

      <div className="px-2.5 py-1.5 rounded-lg bg-[#1E1C1A] border border-[#3D3A36] text-xs flex items-center justify-between">
        <span className="font-medium text-[#B4ADA5]">Portal Context</span>
        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-[#C66A32]/20 text-[#E69A45] border border-[#C66A32]/30 capitalize">
          {role === "examiner" ? "Examiner Board" : "Student Services"}
        </span>
      </div>

      <nav aria-label="Primary" className="flex flex-col gap-1">
        <p className="mb-1 px-2 text-[10px] font-bold uppercase tracking-wider text-[#8E867E]">Navigation</p>
        {navItems.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex items-center justify-between rounded-lg px-3 py-2.5 text-xs font-semibold text-[#B4ADA5] transition-all hover:bg-[#34312E] hover:text-[#F7F4EF] [&_svg]:size-4",
                isActive && "bg-[#C66A32] text-white font-bold shadow-sm"
              )
            }
          >
            <span className="flex items-center gap-2.5">
              {n.icon}
              {n.label}
            </span>
            {Boolean("withBadge" in n && n.withBadge && pendingCount > 0) ? (
              <span className="px-1.5 py-0.5 text-[10px] font-bold rounded-full bg-[#E69A45] text-[#292725]">
                {pendingCount}
              </span>
            ) : null}
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto space-y-3 pt-2">
        <ServiceStatus />
        <div className="rounded-xl border border-[#3D3A36] bg-[#1E1C1A] p-3 text-[11px] leading-relaxed text-[#B4ADA5]">
          <p className="font-semibold text-[#F7F4EF] mb-1">Governance Rule</p>
          AI generates recommendations only. Every petition is decided by a designated university examination officer.
        </div>
      </div>
    </div>
  );
}

function SheetCloseWrap({ role }: { role: "student" | "examiner" }) {
  return (
    <SheetClose asChild>
      <div className="h-full">
        <SidebarBody role={role} />
      </div>
    </SheetClose>
  );
}

export function AppShell() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { user, isAuthenticated, isLoading, logout } = useAuth();
  const { dark, toggle } = useTheme();

  // Role resolution
  const isExaminerPath = pathname.startsWith("/examiner") || pathname.startsWith("/monitor");
  const isStudentPath = pathname.startsWith("/student");
  const currentRole: "student" | "examiner" = isExaminerPath ? "examiner" : "student";

  // Enforce genuine authentication & route access control
  useEffect(() => {
    if (isLoading) return;

    if (!isAuthenticated) {
      if (isExaminerPath) {
        navigate("/examiner/login", { replace: true });
      } else if (isStudentPath) {
        navigate("/student/login", { replace: true });
      }
      return;
    }

    // Role-based route protection: student cannot access examiner or monitor pages
    if (user?.role === "student" && isExaminerPath) {
      toast.error("Examiner portal is restricted to academic board members.");
      navigate("/student/dashboard", { replace: true });
    }
  }, [isAuthenticated, isLoading, user, pathname, isExaminerPath, isStudentPath, navigate]);

  const handleSignOut = async () => {
    await logout();
    toast.info("Signed out successfully.");
    navigate("/", { replace: true });
  };

  if (isLoading) {
    return (
      <div className="min-h-screen grid place-items-center bg-background">
        <div className="text-center space-y-3">
          <div className="size-10 border-3 border-brand border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-xs text-muted-foreground font-medium">Verifying security credentials…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Desktop Persistent Sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r border-[#3D3A36] bg-[#292725] md:block z-20 shadow-md">
        <SidebarBody role={currentRole} />
      </aside>

      <div className="md:pl-64">
        {/* Top Header */}
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-4 border-b bg-card/90 px-4 backdrop-blur md:px-8 shadow-xs">
          {/* Mobile Sheet Trigger */}
          <div className="flex items-center gap-3">
            <Sheet>
              <SheetTrigger className="rounded-lg p-2 hover:bg-muted md:hidden border" aria-label="Open navigation menu">
                <Menu className="size-5" />
              </SheetTrigger>
              <SheetContent title="Navigation" className="p-0 border-[#3D3A36] bg-[#292725]">
                <SheetCloseWrap role={currentRole} />
              </SheetContent>
            </Sheet>

            <div className="hidden sm:flex items-center gap-2">
              <span className="text-xs font-semibold tracking-tight text-foreground">
                {currentRole === "examiner" ? "Academic Examination Board" : "Student Academic Services"}
              </span>
              <span className="text-muted-foreground">•</span>
              <span className="text-xs text-muted-foreground capitalize">
                {pathname.split("/")[2] || "overview"}
              </span>
            </div>
          </div>

          {/* Right Header: User Details & Controls */}
          <div className="flex items-center gap-3">
            {/* Theme Toggle */}
            <button
              type="button"
              onClick={toggle}
              className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground border transition-colors"
              aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
            >
              {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </button>

            {/* Authenticated User Pill */}
            {user && (
              <div className="flex items-center gap-2 pl-2 py-1 pr-1.5 rounded-full border bg-muted/40">
                <NavLink
                  to={currentRole === "student" ? "/student/profile" : "/examiner/dashboard"}
                  className="flex items-center gap-2 hover:opacity-85 transition-opacity"
                  title={currentRole === "student" ? "View Student Profile" : user.name}
                >
                  <div className="size-7 rounded-full bg-brand text-white flex items-center justify-center text-xs font-bold shadow-sm">
                    {user.name.split(" ").map((n) => n[0]).slice(0, 2).join("")}
                  </div>
                  <div className="text-left hidden lg:block pr-1 leading-tight">
                    <p className="text-xs font-bold text-foreground leading-none">{user.name}</p>
                    <p className="text-[10px] text-muted-foreground font-mono leading-none mt-0.5">{user.user_id}</p>
                  </div>
                </NavLink>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleSignOut}
                  className="size-7 p-0 rounded-full text-muted-foreground hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950/50"
                  title="Sign Out"
                >
                  <LogOut className="size-3.5" />
                </Button>
              </div>
            )}
          </div>
        </header>

        {/* Main Workspace Body */}
        <main id="main" className="mx-auto w-full max-w-6xl px-4 py-6 md:px-8 md:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
