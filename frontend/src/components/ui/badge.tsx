import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap", {
  variants: {
    tone: {
      neutral: "border-transparent bg-secondary text-secondary-foreground",
      success: "border-transparent bg-success-soft text-success",
      warning: "border-transparent bg-warning-soft text-warning",
      danger: "border-transparent bg-danger-soft text-danger",
      info: "border-transparent bg-info-soft text-info",
      outline: "text-muted-foreground",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {
  variant?: "outline" | "secondary" | "default" | "destructive" | string;
  dot?: boolean;
}

export function Badge({ className, tone, variant, dot, children, ...p }: BadgeProps) {
  const resolvedTone = tone ?? (variant === "outline" ? "outline" : variant === "destructive" ? "danger" : "neutral");
  return (
    <span className={cn(badgeVariants({ tone: resolvedTone as any }), className)} {...p}>
      {dot && <span className="size-1.5 rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  );
}
