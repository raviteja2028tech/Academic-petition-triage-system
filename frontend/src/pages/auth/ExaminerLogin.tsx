import { ArrowLeft, Eye, EyeOff, Gavel, KeyRound, Lock, ShieldCheck, User } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/lib/authContext";

export function ExaminerLogin() {
  const navigate = useNavigate();
  const location = useLocation();
  const { examinerLogin, isAuthenticated, role } = useAuth();

  const [examinerId, setExaminerId] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // If already logged in as examiner, redirect
  useEffect(() => {
    if (isAuthenticated && role === "examiner" && location.pathname.includes("/login")) {
      navigate("/examiner/dashboard", { replace: true });
    }
  }, [isAuthenticated, role, navigate, location.pathname]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    const cleanId = examinerId.trim().toUpperCase();
    if (!cleanId) {
      setErrorMessage("Please enter your Examiner ID.");
      return;
    }
    if (!password) {
      setErrorMessage("Please enter your password.");
      return;
    }

    setIsLoading(true);
    try {
      const user = await examinerLogin(cleanId, password);
      toast.success(`Welcome, Examiner ${user.name}`);
      navigate("/examiner/dashboard", { replace: true });
    } catch (err: any) {
      const msg = err?.message || "Invalid Examiner ID or password. Access denied.";
      setErrorMessage(msg);
      toast.error(msg);
    } finally {
      setIsLoading(false);
    }
  };

  const handleFillDemo = (id = "EXM2026001") => {
    setExaminerId(id);
    setPassword("Examiner@123");
    setErrorMessage(null);
    toast.info(`Loaded demo credentials for ${id}`);
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col justify-center items-center px-4 py-8 relative">
      {/* Background Subtle Warm Radial Tint */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(41,39,37,0.08),rgba(247,244,239,0))] dark:bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(230,154,69,0.08),rgba(0,0,0,0))] pointer-events-none" />

      {/* Back to Gateway */}
      <div className="w-full max-w-md mb-4 flex items-center justify-between z-10">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="size-3.5" />
          Back to Portal Selection
        </Link>
        <span className="text-xs font-semibold text-amber-700 dark:text-amber-400 bg-amber-500/10 px-2.5 py-0.5 rounded-full border border-amber-500/20 flex items-center gap-1">
          <ShieldCheck className="size-3" />
          Examiner Board
        </span>
      </div>

      <Card className="w-full max-w-md border border-[#3D3A36]/20 dark:border-[#3D3A36] shadow-xl relative z-10 bg-[#292725] text-[#F7F4EF] overflow-hidden">
        {/* Warm Burnt Orange to Amber executive line */}
        <div className="h-1.5 w-full bg-gradient-to-r from-[#C66A32] via-[#E69A45] to-[#C66A32]" />

        <CardHeader className="text-center pt-8 pb-4">
          <div className="size-14 rounded-2xl bg-[#3D3A36] text-[#E69A45] mx-auto flex items-center justify-center mb-3 shadow-md border border-[#4D4944]">
            <Gavel className="size-7" />
          </div>
          <CardTitle className="text-2xl font-bold tracking-tight text-[#F7F4EF]">Examiner Board Portal</CardTitle>
          <CardDescription className="text-xs md:text-sm text-[#B4ADA5] mt-1">
            Sign in to review academic petitions, examine AI citations, and issue official determinations
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4 pt-2">
          {errorMessage && (
            <div className="p-3 rounded-lg bg-red-950/70 border border-red-800 text-xs text-red-200 flex items-start gap-2">
              <span className="font-semibold">Error:</span> {errorMessage}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="examinerId" className="text-xs font-semibold text-[#E5DFD7] flex items-center justify-between">
                <span>Examiner ID</span>
                <span className="text-[11px] font-normal text-[#B4ADA5]">Format: EXM2026001</span>
              </label>
              <div className="relative">
                <User className="size-4 absolute left-3 top-3 text-[#B4ADA5] pointer-events-none" />
                <input
                  id="examinerId"
                  type="text"
                  value={examinerId}
                  onChange={(e) => setExaminerId(e.target.value.toUpperCase())}
                  placeholder="e.g. EXM2026001"
                  autoComplete="username"
                  required
                  className="w-full rounded-md border border-[#4D4944] bg-[#1E1C1A] pl-9 pr-3 py-2 text-sm text-[#F7F4EF] placeholder:text-[#77716A] focus:border-[#E69A45] focus:ring-1 focus:ring-[#E69A45] outline-none transition-all uppercase placeholder:normal-case font-mono"
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <label htmlFor="password" className="text-xs font-semibold text-[#E5DFD7]">
                Password
              </label>
              <div className="relative">
                <Lock className="size-4 absolute left-3 top-3 text-[#B4ADA5] pointer-events-none" />
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter examiner password"
                  autoComplete="current-password"
                  required
                  className="w-full rounded-md border border-[#4D4944] bg-[#1E1C1A] pl-9 pr-10 py-2 text-sm text-[#F7F4EF] placeholder:text-[#77716A] focus:border-[#E69A45] focus:ring-1 focus:ring-[#E69A45] outline-none transition-all"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="absolute right-3 top-2.5 text-[#B4ADA5] hover:text-[#F7F4EF] transition-colors"
                >
                  {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
            </div>

            <div className="p-2.5 rounded-md bg-[#1E1C1A] border border-[#3D3A36] text-[11px] text-[#B4ADA5] flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <ShieldCheck className="size-3.5 text-[#E69A45]" />
                Role-Restricted Board Access
              </span>
              <span className="text-[#8E867E]">Argon2/bcrypt Hash</span>
            </div>

            <Button
              type="submit"
              disabled={isLoading}
              className="w-full bg-[#C66A32] hover:bg-[#B35922] text-white font-semibold py-2.5 shadow-md transition-all cursor-pointer"
            >
              {isLoading ? "Validating Credentials…" : "Sign In to Examiner Portal"}
            </Button>
          </form>

          {/* Quick Demo Credentials Helper */}
          <div className="pt-3 border-t border-[#3D3A36]">
            <div className="rounded-lg bg-[#1E1C1A] border border-[#3D3A36] p-3 space-y-2.5">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-[#E5DFD7]">
                <KeyRound className="size-3.5 text-[#E69A45]" />
                Select Demo Examiner (Password: <code className="font-mono text-[#F7F4EF] font-bold">Examiner@123</code>)
              </div>
              <div className="grid grid-cols-2 gap-2">
                {[
                  { id: "EXM2026001", name: "Dr. Eleanor Vance", role: "Board Chair" },
                  { id: "EXM2026002", name: "Prof. Rajesh Kulkarni", role: "Secretary" },
                ].map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    aria-label={`Fill ${m.id}`}
                    onClick={() => handleFillDemo(m.id)}
                    className="flex flex-col items-center justify-center p-2 rounded-lg border border-[#3D3A36] bg-[#292725] hover:bg-[#34312E] hover:border-[#E69A45]/40 text-[#F7F4EF] transition-all text-center cursor-pointer"
                  >
                    <span className="font-mono text-xs font-bold text-[#E69A45]">{m.id}</span>
                    <span className="text-[11px] font-medium text-[#E5DFD7]">{m.name}</span>
                    <span className="text-[9px] text-[#B4ADA5]">{m.role}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </CardContent>

        <CardFooter className="bg-[#1E1C1A] border-t border-[#3D3A36] py-3.5 text-center text-xs text-[#B4ADA5] flex justify-center">
          <span>Are you a student?</span>
          <Link to="/student/login" className="ml-1 text-[#E69A45] hover:underline font-medium">Go to Student Portal</Link>
        </CardFooter>
      </Card>

      <p className="mt-6 text-center text-[11px] text-muted-foreground max-w-sm leading-relaxed">
        <strong>Notice:</strong> This interface is reserved for appointed examiners. All decision actions are cryptographically logged and attributed to the signing officer.
      </p>
    </div>
  );
}
