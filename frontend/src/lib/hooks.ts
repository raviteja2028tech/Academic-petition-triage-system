import { useCallback, useEffect, useState } from "react";

function safeGet(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function safeSet(key: string, v: string) {
  try { localStorage.setItem(key, v); } catch { /* storage unavailable: keep working in memory */ }
}

export function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const toggle = useCallback(() => {
    setDark((d) => {
      const next = !d;
      document.documentElement.classList.toggle("dark", next);
      safeSet("theme", next ? "dark" : "light");
      return next;
    });
  }, []);
  return { dark, toggle };
}

/** The student "identity" is only a synthetic reference kept in this browser. It is NOT a login. */
export function useStudentRef() {
  const [ref, setRef] = useState(() => safeGet("student_ref") ?? "");
  const save = useCallback((v: string) => { setRef(v); safeSet("student_ref", v); }, []);
  return [ref, save] as const;
}

export function useExaminerLabel() {
  const [label, setLabel] = useState(() => safeGet("examiner_label") ?? "");
  const save = useCallback((v: string) => { setLabel(v); safeSet("examiner_label", v); }, []);
  return [label, save] as const;
}

export function useDocumentTitle(title: string) {
  useEffect(() => { document.title = `${title} · Petition Triage`; }, [title]);
}
