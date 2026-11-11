import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { titleCase } from "@/lib/utils";

const PALETTE = ["hsl(173 70% 38%)", "hsl(221 75% 55%)", "hsl(30 90% 50%)", "hsl(0 70% 55%)", "hsl(262 55% 58%)", "hsl(152 55% 40%)", "hsl(215 15% 55%)"];
const axis = { fontSize: 11, fill: "hsl(var(--muted-foreground))" };
const tip = { contentStyle: { background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }, labelStyle: { fontWeight: 600 } };

export function ChartEmpty({ children = "No data yet" }: { children?: string }) {
  return <div className="grid h-full min-h-[160px] place-items-center rounded-md border border-dashed text-sm text-muted-foreground">{children}</div>;
}

export function HBar({ data, height = 220, format }: { data: Record<string, number>; height?: number; format?: (k: string) => string }) {
  const rows = Object.entries(data).map(([k, v]) => ({ name: (format ?? titleCase)(k), value: v })).sort((a, b) => b.value - a.value);
  if (!rows.length) return <ChartEmpty />;
  return (
    <div style={{ height: Math.max(height, rows.length * 34) }} role="img" aria-label={`Bar chart: ${rows.map((r) => `${r.name} ${r.value}`).join(", ")}`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }}>
          <CartesianGrid horizontal={false} stroke="hsl(var(--border))" />
          <XAxis type="number" allowDecimals={false} tick={axis} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" width={150} tick={axis} axisLine={false} tickLine={false} />
          <Tooltip {...tip} cursor={{ fill: "hsl(var(--muted))" }} />
          <Bar dataKey="value" radius={[0, 4, 4, 0]} fill={PALETTE[0]} barSize={16} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Donut({ data, height = 220 }: { data: Record<string, number>; height?: number }) {
  const rows = Object.entries(data).filter(([, v]) => v > 0).map(([k, v]) => ({ name: titleCase(k), value: v }));
  if (!rows.length) return <ChartEmpty />;
  const total = rows.reduce((a, r) => a + r.value, 0);
  return (
    <div className="flex flex-wrap items-center gap-4" role="img" aria-label={`Distribution: ${rows.map((r) => `${r.name} ${r.value}`).join(", ")}`}>
      <div style={{ width: height, height }} className="relative shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={rows} dataKey="value" nameKey="name" innerRadius="62%" outerRadius="92%" paddingAngle={2} stroke="none">
              {rows.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
            </Pie>
            <Tooltip {...tip} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 grid place-items-center text-center"><div><p className="text-2xl font-semibold tabular-nums">{total}</p><p className="text-[11px] text-muted-foreground">petitions</p></div></div>
      </div>
      <ul className="min-w-[120px] flex-1 space-y-1.5 text-sm">
        {rows.map((r, i) => (
          <li key={r.name} className="flex items-center gap-2"><span className="size-2.5 rounded-sm" style={{ background: PALETTE[i % PALETTE.length] }} aria-hidden /><span className="flex-1">{r.name}</span><span className="font-mono text-xs tabular-nums text-muted-foreground">{r.value}</span></li>
        ))}
      </ul>
    </div>
  );
}

export function TrendArea({ data, height = 220 }: { data: Record<string, { total: number; escalated: number }>; height?: number }) {
  const rows = Object.entries(data).map(([day, v]) => ({ day: day.slice(5), total: v.total, escalated: v.escalated }));
  if (rows.length < 1) return <ChartEmpty />;
  return (
    <div style={{ height }} role="img" aria-label="Petitions and escalations per day">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ left: -16, right: 8, top: 8, bottom: 0 }}>
          <defs>
            <linearGradient id="gt" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={PALETTE[1]} stopOpacity={0.3} /><stop offset="100%" stopColor={PALETTE[1]} stopOpacity={0} /></linearGradient>
            <linearGradient id="ge" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={PALETTE[2]} stopOpacity={0.35} /><stop offset="100%" stopColor={PALETTE[2]} stopOpacity={0} /></linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="hsl(var(--border))" />
          <XAxis dataKey="day" tick={axis} axisLine={false} tickLine={false} />
          <YAxis allowDecimals={false} tick={axis} axisLine={false} tickLine={false} />
          <Tooltip {...tip} />
          <Area type="monotone" dataKey="total" name="Petitions" stroke={PALETTE[1]} fill="url(#gt)" strokeWidth={2} />
          <Area type="monotone" dataKey="escalated" name="Escalated" stroke={PALETTE[2]} fill="url(#ge)" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ValueBars({ rows, unit, height = 220 }: { rows: { name: string; value: number | null }[]; unit?: string; height?: number }) {
  const data = rows.filter((r) => r.value != null).map((r) => ({ name: titleCase(r.name), value: r.value as number }));
  if (!data.length) return <ChartEmpty />;
  return (
    <div style={{ height }} role="img" aria-label={`Chart: ${data.map((r) => `${r.name} ${r.value}${unit ?? ""}`).join(", ")}`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ left: -12, right: 8, top: 8, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="hsl(var(--border))" />
          <XAxis dataKey="name" tick={axis} axisLine={false} tickLine={false} interval={0} />
          <YAxis tick={axis} axisLine={false} tickLine={false} unit={unit} />
          <Tooltip {...tip} cursor={{ fill: "hsl(var(--muted))" }} formatter={(v: number) => `${v}${unit ?? ""}`} />
          <Bar dataKey="value" radius={[4, 4, 0, 0]} fill={PALETTE[0]} barSize={28} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
