import { ArrowLeft, Eye, EyeOff, GraduationCap, KeyRound, Lock, ShieldCheck, User } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/lib/authContext";

export function StudentLogin() {
  const navigate = useNavigate();
  const location = useLocation();
  const { studentLogin, isAuthenticated, role } = useAuth();

  const [studentId, setStudentId] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [showForgotModal, setShowForgotModal] = useState(false);

  // If already logged in as student, redirect
  useEffect(() => {
    if (isAuthenticated && role === "student" && location.pathname.includes("/login")) {
      navigate("/student/dashboard", { replace: true });
    }
  }, [isAuthenticated, role, navigate, location.pathname]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    const cleanId = studentId.trim().toUpperCase();
    if (!cleanId) {
      setErrorMessage("Please enter your Student ID.");
      return;
    }
    if (!password) {
      setErrorMessage("Please enter your password.");
      return;
    }

    setIsLoading(true);
    try {
      const user = await studentLogin(cleanId, password);
      toast.success(`Welcome back, ${user.name}!`);
      navigate("/student/dashboard", { replace: true });
    } catch (err: any) {
      const msg = err?.message || "Invalid Student ID or password. Please verify your credentials.";
      setErrorMessage(msg);
      toast.error(msg);
    } finally {
      setIsLoading(false);
    }
  };

  const handleFillDemo = (id = "STU2026001") => {
    setStudentId(id);
    setPassword("Student@123");
    setErrorMessage(null);
    toast.info(`Loaded demo credentials for ${id}`);
  };

  return (
    <div className="min-h-screen bg-background flex flex-col justify-center items-center px-4 py-8 relative">
      {/* Background Subtle Warm Radial Tint */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(198,106,50,0.12),rgba(247,244,239,0))] dark:bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(198,106,50,0.08),rgba(0,0,0,0))] pointer-events-none" />

      {/* Back to Gateway */}
      <div className="w-full max-w-md mb-4 flex items-center justify-between z-10">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="size-3.5" />
          Back to Portal Selection
        </Link>
        <span className="text-xs font-semibold text-brand bg-brand/10 px-2.5 py-0.5 rounded-full border border-brand/20">
          Student Services
        </span>
      </div>

      <Card className="w-full max-w-md border shadow-lg relative z-10 bg-card overflow-hidden">
        {/* Color accent line */}
        <div className="h-1.5 w-full bg-gradient-to-r from-brand via-amber-500 to-brand" />

        <CardHeader className="text-center pt-8 pb-4">
          <div className="size-14 rounded-2xl bg-brand/10 text-brand mx-auto flex items-center justify-center mb-3 shadow-xs border border-brand/20">
            <GraduationCap className="size-7" />
          </div>
          <CardTitle className="text-2xl font-bold tracking-tight text-foreground">Student Portal Login</CardTitle>
          <CardDescription className="text-xs md:text-sm text-muted-foreground mt-1">
            Access your academic petitions, submit evidence, and view official decisions
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4 pt-2">
          {errorMessage && (
            <div className="p-3 rounded-lg bg-red-50 dark:bg-red-950/50 border border-red-200 dark:border-red-900/60 text-xs text-red-700 dark:text-red-300 flex items-start gap-2">
              <span className="font-semibold">Error:</span> {errorMessage}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="studentId" className="text-xs font-semibold text-foreground flex items-center justify-between">
                <span>Student ID</span>
                <span className="text-[11px] font-normal text-muted-foreground">Format: STU2026001</span>
              </label>
              <div className="relative">
                <User className="size-4 absolute left-3 top-3 text-muted-foreground pointer-events-none" />
                <input
                  id="studentId"
                  type="text"
                  value={studentId}
                  onChange={(e) => setStudentId(e.target.value.toUpperCase())}
                  placeholder="e.g. STU2026001"
                  autoComplete="username"
                  required
                  className="w-full rounded-md border border-input bg-background pl-9 pr-3 py-2 text-sm focus:border-brand focus:ring-1 focus:ring-brand outline-none transition-all uppercase placeholder:normal-case font-mono"
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label htmlFor="password" className="text-xs font-semibold text-foreground">
                  Password
                </label>
                <button
                  type="button"
                  onClick={() => setShowForgotModal(true)}
                  className="text-xs text-brand hover:underline font-medium"
                >
                  Forgot password?
                </button>
              </div>
              <div className="relative">
                <Lock className="size-4 absolute left-3 top-3 text-muted-foreground pointer-events-none" />
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter your student password"
                  autoComplete="current-password"
                  required
                  className="w-full rounded-md border border-input bg-background pl-9 pr-10 py-2 text-sm focus:border-brand focus:ring-1 focus:ring-brand outline-none transition-all"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="absolute right-3 top-2.5 text-muted-foreground hover:text-foreground transition-colors"
                >
                  {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
            </div>

            <div className="flex items-center justify-between text-xs pt-1">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                  className="size-3.5 rounded border-input accent-brand"
                />
                <span className="text-muted-foreground">Keep me signed in</span>
              </label>

              <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                <ShieldCheck className="size-3 text-emerald-500" />
                Encrypted Session
              </span>
            </div>

            <Button
              type="submit"
              disabled={isLoading}
              className="w-full bg-brand hover:bg-brand/90 text-white font-medium py-2.5 shadow-sm transition-all"
            >
              {isLoading ? "Authenticating…" : "Sign In to Student Portal"}
            </Button>
          </form>

          {/* Quick Demo Credentials Helper */}
          <div className="pt-3 border-t">
            <div className="rounded-lg bg-brand/5 border border-brand/20 p-3 space-y-2.5">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                <KeyRound className="size-3.5 text-brand" />
                Select Demo Student (Password: <code className="font-mono text-foreground font-bold">Student@123</code>)
              </div>
              <div className="grid grid-cols-3 gap-1.5">
                {[
                  { id: "STU2026001", name: "Alex (CSE)", desc: "Decided cases" },
                  { id: "STU2026002", name: "Priya (ISE)", desc: "Awaiting review" },
                  { id: "STU2026003", name: "Marcus (ECE)", desc: "Info requested" },
                ].map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    aria-label={`Fill ${s.id}`}
                    onClick={() => handleFillDemo(s.id)}
                    className="flex flex-col items-center justify-center p-2 rounded-lg border bg-card hover:bg-muted/80 text-foreground transition-all shadow-xs text-center"
                  >
                    <span className="font-mono text-xs font-bold text-brand">{s.id}</span>
                    <span className="text-[10px] font-medium text-foreground">{s.name}</span>
                    <span className="text-[9px] text-muted-foreground">{s.desc}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </CardContent>

        <CardFooter className="bg-slate-50/80 dark:bg-slate-900/40 border-t py-3.5 text-center text-xs text-muted-foreground flex justify-center">
          <span>Need help or examiner access?</span>
          <Link to="/examiner/login" className="ml-1 text-brand hover:underline font-medium">Examiner Portal</Link>
        </CardFooter>
      </Card>

      {/* Forgot Password Dialog */}
      {showForgotModal && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-card max-w-sm w-full rounded-xl p-6 shadow-2xl border space-y-4">
            <h3 className="text-lg font-bold text-foreground">Password Recovery</h3>
            <p className="text-xs text-muted-foreground leading-relaxed">
              In this university demonstration environment, passwords are securely hashed using bcrypt.
            </p>
            <div className="p-3 bg-muted rounded-md text-xs space-y-1 font-mono">
              <p>Demo ID: <strong>STU2026001</strong></p>
              <p>Demo Password: <strong>Student@123</strong></p>
            </div>
            <p className="text-xs text-muted-foreground">
              For production reset assistance, please contact the University IT Service Desk or Registrar Office.
            </p>
            <Button className="w-full" onClick={() => setShowForgotModal(false)}>
              Got it
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
