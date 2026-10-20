import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { cx } from "./ui";

export interface Option {
  value: number;
  label: string;
}

/** Seleção múltipla com busca na API (CNAEs, municípios). */
export function AsyncPicker({
  path,
  toOption,
  selected,
  onChange,
  placeholder,
  extraQuery,
}: {
  path: string;
  toOption: (row: Record<string, unknown>) => Option;
  selected: Option[];
  onChange: (opts: Option[]) => void;
  placeholder: string;
  extraQuery?: Record<string, string>;
}) {
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setTerm(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);
  const res = useQuery({
    queryKey: [path, term, extraQuery],
    queryFn: () => api<Record<string, unknown>[]>(path, { query: { q: term, limite: 15, ...extraQuery } }),
    enabled: term.length >= 2,
  });
  const options = (res.data ?? []).map(toOption).filter((o) => !selected.some((s) => s.value === o.value));

  return (
    <div className="relative">
      <div className="flex min-h-[38px] flex-wrap items-center gap-1 rounded-md bg-white px-2 py-1 ring-1 ring-slate-300 focus-within:ring-2 focus-within:ring-brand-500">
        {selected.map((s) => (
          <span key={s.value} className="inline-flex items-center gap-1 rounded bg-brand-50 px-1.5 py-0.5 text-xs text-brand-700">
            {s.label}
            <button type="button" aria-label={`Remover ${s.label}`} onClick={() => onChange(selected.filter((x) => x.value !== s.value))}>
              ×
            </button>
          </span>
        ))}
        <input
          className="min-w-24 flex-1 border-0 bg-transparent py-1 text-sm focus:outline-none"
          value={q}
          placeholder={selected.length ? "" : placeholder}
          aria-label={placeholder}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
        />
      </div>
      {open && term.length >= 2 && (
        <ul className="absolute z-[1100] mt-1 max-h-64 w-full overflow-auto rounded-md border border-slate-200 bg-white py-1 text-sm shadow-lg">
          {res.isLoading && <li className="px-3 py-1.5 text-slate-500">Buscando…</li>}
          {!res.isLoading && options.length === 0 && <li className="px-3 py-1.5 text-slate-500">Nada encontrado</li>}
          {options.map((o) => (
            <li key={o.value}>
              <button
                type="button"
                className={cx("block w-full px-3 py-1.5 text-left hover:bg-brand-50")}
                onMouseDown={(e) => {
                  e.preventDefault();
                  onChange([...selected, o]);
                  setQ("");
                }}
              >
                {o.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
