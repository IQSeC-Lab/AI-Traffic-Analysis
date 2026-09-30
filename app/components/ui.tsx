import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import { AlertTriangle, Info, Loader2, XCircle } from "lucide-react";

// ── Layout ───────────────────────────────────────────────────────────────────

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-ink-2">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({
  title,
  description,
  action,
  children,
  id,
  className = "",
  padded = true,
}: {
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  id?: string;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section
      id={id}
      className={`scroll-mt-6 rounded-2xl border border-hairline bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.04)] ${className}`}
    >
      {(title || action) && (
        <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5">
          <div>
            {title && <h2 className="text-sm font-semibold">{title}</h2>}
            {description && <p className="mt-0.5 text-sm text-ink-3">{description}</p>}
          </div>
          {action}
        </div>
      )}
      <div className={padded ? "p-5" : ""}>{children}</div>
    </section>
  );
}

// ── Controls ─────────────────────────────────────────────────────────────────

const buttonStyles = {
  primary: "bg-accent-strong text-white hover:bg-accent-strong-hover shadow-sm",
  secondary: "border border-hairline bg-surface text-ink hover:bg-surface-2",
  ghost: "text-ink-2 hover:bg-surface-2 hover:text-ink",
  danger: "bg-critical text-white hover:bg-critical-hover shadow-sm",
};

export function buttonClass(variant: keyof typeof buttonStyles = "primary", size: "sm" | "md" = "md") {
  const sizes = size === "sm" ? "h-8 px-3 text-xs" : "h-9 px-4 text-sm";
  return `inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 ${sizes} ${buttonStyles[variant]}`;
}

export function ButtonLink({
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: ComponentProps<typeof Link> & { variant?: keyof typeof buttonStyles; size?: "sm" | "md" }) {
  return <Link {...props} className={`${buttonClass(variant, size)} ${className}`} />;
}

export const inputClass =
  "h-9 w-full rounded-lg border border-hairline bg-surface px-3 text-sm outline-none transition-shadow placeholder:text-ink-3 focus:border-accent focus:ring-4 focus:ring-accent/15";

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs text-ink-3">{hint}</span>}
    </label>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="inline-flex rounded-lg bg-surface-2 p-0.5 text-xs">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={`rounded-md px-2.5 py-1 font-medium transition-colors ${
            o.value === value ? "bg-surface text-ink shadow-sm" : "text-ink-3 hover:text-ink"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ── Data display ─────────────────────────────────────────────────────────────

export function StatTile({
  label,
  value,
  hint,
  className = "",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-2xl border border-hairline bg-surface p-4 shadow-[0_1px_2px_rgba(0,0,0,0.04)] ${className}`}>
      <div className="text-xs font-medium text-ink-3">{label}</div>
      <div className="mt-2 text-2xl font-semibold tracking-tight">{value}</div>
      {hint && <div className="mt-1 text-xs text-ink-3">{hint}</div>}
    </div>
  );
}

export function ProgressBar({ value, max, tone = "accent" }: { value: number; max: number; tone?: "accent" | "good" }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-accent-wash">
      <div
        className={`h-full rounded-full transition-[width] duration-500 ${tone === "good" ? "bg-good" : "bg-accent"}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// `live` statuses pulse: something is happening right now
const STATUS: Record<string, { label: string; color: string; live?: boolean }> = {
  pending: { label: "Starting", color: "var(--accent)", live: true },
  running: { label: "Running", color: "var(--accent)", live: true },
  cancelling: { label: "Cancelling", color: "var(--warning)", live: true },
  cleaning_up: { label: "Cleaning up", color: "var(--warning)", live: true },
  completed: { label: "Completed", color: "var(--good)" },
  failed: { label: "Failed", color: "var(--critical)" },
  cancelled: { label: "Cancelled", color: "var(--ink-3)" },
  interrupted: { label: "Interrupted", color: "var(--serious)" },
  queued: { label: "Queued", color: "var(--ink-3)" },
  preparing: { label: "Preparing", color: "var(--accent)", live: true },
  downloading: { label: "Downloading", color: "var(--accent)", live: true },
};

export function LiveDot({ color = "var(--accent)" }: { color?: string }) {
  return (
    <span className="relative inline-flex h-2 w-2">
      <span
        className="absolute inline-flex h-full w-full rounded-full"
        style={{ background: color, animation: "live-ping 1.6s cubic-bezier(0,0,0.2,1) infinite" }}
      />
      <span className="relative inline-flex h-2 w-2 rounded-full" style={{ background: color }} />
    </span>
  );
}

/** Status is carried by a dot and its label, never color alone. Live states pulse. */
export function StatusPill({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, color: "var(--ink-3)" };
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-surface px-2 py-0.5 text-xs font-medium text-ink-2">
      {s.live ? (
        <LiveDot color={s.color} />
      ) : (
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: s.color }} />
      )}
      {s.label}
    </span>
  );
}

export function Alert({
  tone = "critical",
  children,
}: {
  tone?: "critical" | "warning" | "info";
  children: ReactNode;
}) {
  const tones = {
    critical: { icon: XCircle, color: "var(--critical)" },
    warning: { icon: AlertTriangle, color: "var(--serious)" },
    info: { icon: Info, color: "var(--accent)" },
  };
  const { icon: Icon, color } = tones[tone];
  return (
    <div className="flex gap-2.5 rounded-xl border border-hairline bg-surface-2 px-3.5 py-3 text-sm text-ink-2">
      <Icon className="mt-0.5 h-4 w-4 shrink-0" style={{ color }} strokeWidth={2} />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-dashed border-hairline px-6 py-14 text-center">
      <h3 className="text-sm font-semibold">{title}</h3>
      {children && <p className="mt-1 max-w-sm text-sm text-ink-3">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return <Loader2 className={`animate-spin ${className}`} strokeWidth={2} />;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-sm text-ink-3">
      <Spinner /> {label}
    </div>
  );
}
