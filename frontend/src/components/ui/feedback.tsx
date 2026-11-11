import type * as React from "react";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("relative overflow-hidden rounded-md bg-muted before:absolute before:inset-0 before:-translate-x-full before:animate-[shimmer_1.6s_infinite] before:bg-gradient-to-r before:from-transparent before:via-foreground/5 before:to-transparent", className)} />;
}

type Tone = "info" | "success" | "warning" | "danger";
const tones: Record<Tone, { box: string; icon: React.ReactNode }> = {
  info: { box: "bg-info-soft text-info border-info/20", icon: <Info className="size-4" /> },
  success: { box: "bg-success-soft text-success border-success/20", icon: <CheckCircle2 className="size-4" /> },
  warning: { box: "bg-warning-soft text-warning border-warning/25", icon: <AlertTriangle className="size-4" /> },
  danger: { box: "bg-danger-soft text-danger border-danger/20", icon: <XCircle className="size-4" /> },
};

export function Callout({ tone = "info", title, children, className }: { tone?: Tone; title?: string; children?: React.ReactNode; className?: string }) {
  const t = tones[tone];
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cn("flex gap-3 rounded-lg border p-3.5 text-sm", t.box, className)}>
      <span className="mt-0.5 shrink-0">{t.icon}</span>
      <div className="min-w-0 space-y-0.5">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className="text-[13px] leading-relaxed opacity-90">{children}</div>}
      </div>
    </div>
  );
}

export function EmptyState({ icon, title, children, action }: { icon?: React.ReactNode; title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-12 text-center">
      {icon && <div className="mb-1 text-muted-foreground [&_svg]:size-8">{icon}</div>}
      <p className="text-sm font-semibold">{title}</p>
      {children && <p className="max-w-sm text-sm text-muted-foreground">{children}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <Callout tone="danger" title="Could not load data">
      <p>{msg}</p>
      {onRetry && (
        <button className="mt-2 text-xs font-semibold underline underline-offset-2" onClick={onRetry}>Try again</button>
      )}
    </Callout>
  );
}
