import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { useEffect } from "react";
import { ApiError } from "../lib/api";

export function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";

const variants: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-500/50",
  secondary: "bg-white text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 disabled:text-slate-400",
  ghost: "text-slate-600 hover:bg-slate-100 disabled:text-slate-300",
  danger: "bg-white text-red-700 ring-1 ring-red-200 hover:bg-red-50",
};

export function Button({
  variant = "primary",
  size = "md",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  return (
    <button
      type="button"
      {...props}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:cursor-not-allowed",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm",
        variants[variant],
        className,
      )}
    />
  );
}

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-xl border border-slate-200 bg-white shadow-sm", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-3">
          <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
          {actions}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

const tones = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  red: "bg-red-50 text-red-700 ring-red-600/20",
  amber: "bg-amber-50 text-amber-800 ring-amber-600/20",
  blue: "bg-brand-50 text-brand-700 ring-brand-600/20",
  gray: "bg-slate-100 text-slate-600 ring-slate-500/20",
};

export function Badge({ tone = "gray", children }: { tone?: keyof typeof tones; children: ReactNode }) {
  return <span className={cx("inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset", tones[tone])}>{children}</span>;
}

export function SituacaoBadge({ situacao }: { situacao: string | null | undefined }) {
  const tone = situacao === "ATIVA" ? "green" : situacao === "BAIXADA" || situacao === "NULA" ? "red" : situacao ? "amber" : "gray";
  return <Badge tone={tone}>{situacao ?? "—"}</Badge>;
}

export function Spinner({ label = "Carregando…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-slate-500" role="status">
      <span className="size-4 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />
      {label}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof ApiError ? error.message : error instanceof Error ? error.message : String(error);
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
      {msg}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-slate-500">{children}</p>;
}

/**
 * Rótulo + controle. Use ``group`` quando o conteúdo tiver vários controles (chips, seleção múltipla):
 * um <label> associaria o texto só ao primeiro botão de dentro.
 */
export function Field({ label, hint, group, children }: { label: string; hint?: string; group?: boolean; children: ReactNode }) {
  const caption = <span className="mb-1 block text-xs font-medium text-slate-600">{label}</span>;
  const help = hint && <span className="mt-1 block text-xs text-slate-400">{hint}</span>;
  if (group) {
    return (
      <div role="group" aria-label={label}>
        {caption}
        {children}
        {help}
      </div>
    );
  }
  return (
    <label className="block">
      {caption}
      {children}
      {help}
    </label>
  );
}

const inputCls =
  "block w-full rounded-md border-0 bg-white py-2 text-sm text-slate-900 ring-1 ring-slate-300 placeholder:text-slate-400 focus:ring-2 focus:ring-brand-500 focus:outline-none";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(inputCls, "px-3", props.className)} />;
}

/** ``compact``: menos espaço lateral, para selects em colunas estreitas. */
export function Select({ compact, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { compact?: boolean }) {
  return <select {...props} className={cx(inputCls, compact ? "pr-6 pl-2" : "pr-8 pl-3", props.className)} />;
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose?: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose?.();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-[1200] flex items-center justify-center bg-slate-900/40 p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className={cx("max-h-[90vh] w-full overflow-auto rounded-xl bg-white shadow-xl", wide ? "max-w-3xl" : "max-w-lg")}>
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <h2 className="font-semibold text-slate-900">{title}</h2>
          {onClose && (
            <button className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" onClick={onClose} aria-label="Fechar">
              ✕
            </button>
          )}
        </header>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string }[]; value: T; onChange: (t: T) => void }) {
  return (
    <nav className="mb-5 flex gap-1 overflow-x-auto border-b border-slate-200" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={cx(
            "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium",
            value === t.id ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800",
          )}
        >
          {t.label}
        </button>
      ))}
    </nav>
  );
}

export function Pagination({ page, hasMore, onChange }: { page: number; hasMore: boolean; onChange: (p: number) => void }) {
  return (
    <div className="flex items-center justify-end gap-2 pt-3 text-sm text-slate-500">
      <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        ← Anterior
      </Button>
      <span>Página {page}</span>
      <Button variant="secondary" size="sm" disabled={!hasMore} onClick={() => onChange(page + 1)}>
        Próxima →
      </Button>
    </div>
  );
}

export function Table({ head, children }: { head: ReactNode[]; children: ReactNode }) {
  return (
    <div className="-mx-5 overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            {head.map((h, i) => (
              <th key={i} className="px-5 py-2 font-medium whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">{children}</tbody>
      </table>
    </div>
  );
}

export function Td({ children, className }: { children: ReactNode; className?: string }) {
  return <td className={cx("px-5 py-2.5 align-top", className)}>{children}</td>;
}

export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
      {items.map(([k, v]) => (
        <div key={k}>
          <dt className="text-xs font-medium text-slate-500">{k}</dt>
          <dd className="mt-0.5 text-sm text-slate-900">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function PageTitle({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
