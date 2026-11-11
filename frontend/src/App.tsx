import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { AppShell } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/feedback";
import { AuthProvider } from "@/lib/authContext";
import { EvaluationPage, SystemOverviewPage } from "@/pages/admin/MonitorPages";
import { ExaminerLogin } from "@/pages/auth/ExaminerLogin";
import { PortalSelect } from "@/pages/auth/PortalSelect";
import { StudentLogin } from "@/pages/auth/StudentLogin";
import { ExaminerDashboard, ExaminerQueue, ExaminerReview } from "@/pages/examiner/ExaminerPages";
import { MyPetitions, NewPetition, StudentHome, StudentPetitionDetail, StudentProfile } from "@/pages/student/StudentPages";

export const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 3000, refetchOnWindowFocus: false } },
});

function NotFound() {
  return (
    <EmptyState
      title="Page not found"
      action={
        <Button asChild variant="outline">
          <Link to="/">Go to Portal Home</Link>
        </Button>
      }
    >
      That page address does not exist.
    </EmptyState>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2"
        >
          Skip to content
        </a>
        <Routes>
          {/* Public Portal Gateway & Distinct Login Routes */}
          <Route path="/" element={<PortalSelect />} />
          <Route path="/student/login" element={<StudentLogin />} />
          <Route path="/examiner/login" element={<ExaminerLogin />} />

          {/* Authenticated Application Shell */}
          <Route element={<AppShell />}>
            {/* Student Portal Routes */}
            <Route path="/student" element={<Navigate to="/student/dashboard" replace />} />
            <Route path="/student/dashboard" element={<StudentHome />} />
            <Route path="/student/new" element={<NewPetition />} />
            <Route path="/student/petitions" element={<MyPetitions />} />
            <Route path="/student/petitions/:id" element={<StudentPetitionDetail />} />
            <Route path="/student/profile" element={<StudentProfile />} />

            {/* Examiner Portal Routes */}
            <Route path="/examiner" element={<Navigate to="/examiner/dashboard" replace />} />
            <Route path="/examiner/dashboard" element={<ExaminerDashboard />} />
            <Route path="/examiner/queue" element={<ExaminerQueue />} />
            <Route path="/examiner/review/:id" element={<ExaminerReview />} />

            {/* Monitoring & Operations Routes */}
            <Route path="/monitor" element={<SystemOverviewPage />} />
            <Route path="/monitor/evaluation" element={<EvaluationPage />} />

            {/* Fallback */}
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
        <Toaster richColors closeButton position="bottom-right" />
      </AuthProvider>
    </QueryClientProvider>
  );
}
