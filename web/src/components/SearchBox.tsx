import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { cleanCnpj, formatCnpj, isValidCnpj } from "../lib/cnpj";
import type { Sugestoes } from "../lib/types";
import { cx } from "./ui";

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

type Item = { key: string; label: string; sub: string; go: () => void };

/** Busca única: CNPJ, razão social, nome fantasia ou sócio, com autocomplete. */
export function SearchBox({ large, autoFocus }: { large?: boolean; autoFocus?: boolean }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const navigate = useNavigate();
  const listId = useId();
  const box = useRef<HTMLDivElement>(null);
  const term = useDebounced(q.trim(), 250);

  const sug = useQuery({
    queryKey: ["sugestoes", term],
    queryFn: () => api<Sugestoes>("/v1/sugestoes", { query: { q: term, limite: 6 } }),
    enabled: term.length >= 3,
    staleTime: 60_000,
  });

  useEffect(() => {
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const reset = () => {
    setOpen(false);
    setQ("");
  };
  const items: Item[] = [
    ...(sug.data?.empresas ?? []).map((e) => ({
      key: `e${e.cnpj}`,
      label: e.razao_social ?? e.nome_fantasia ?? formatCnpj(e.cnpj),
      sub: [formatCnpj(e.cnpj), e.nome_fantasia, e.uf, e.situacao].filter(Boolean).join(" · "),
      go: () => navigate(`/empresa/${e.cnpj}`),
    })),
    ...(sug.data?.socios ?? []).map((s, i) => ({
      key: `s${i}`,
      label: s.nome ?? "—",
      sub: `Sócio ${s.tipo ?? ""} ${s.cpf_cnpj ?? ""}`.trim(),
      go: () => navigate(`/socios?nome=${encodeURIComponent(s.nome ?? "")}${s.cpf_cnpj ? `&cpf=${encodeURIComponent(s.cpf_cnpj.replace(/\D/g, ""))}` : ""}`),
    })),
  ];

  const submit = () => {
    const c = cleanCnpj(q);
    if (c.length === 14 && isValidCnpj(c)) {
      navigate(`/empresa/${c}`);
      reset();
    } else if (items[active]) {
      items[active].go();
      reset();
    } else if (q.trim().length >= 3) {
      navigate(`/busca?q=${encodeURIComponent(q.trim())}`);
      reset();
    }
  };

  const cnpjInvalido = cleanCnpj(q).length === 14 && /^\d+$/.test(cleanCnpj(q)) && !isValidCnpj(q);

  return (
    <div ref={box} className="relative w-full">
      <input
        type="search"
        role="combobox"
        aria-expanded={open && items.length > 0}
        aria-controls={listId}
        aria-label="Buscar por CNPJ, razão social, nome fantasia ou sócio"
        autoFocus={autoFocus}
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, items.length - 1));
          else if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
          else if (e.key === "Enter") submit();
          else if (e.key === "Escape") setOpen(false);
          else return;
          e.preventDefault();
        }}
        placeholder="CNPJ, razão social, nome fantasia ou sócio"
        className={cx(
          "block w-full rounded-lg border-0 bg-white text-slate-900 shadow-sm ring-1 ring-slate-300 placeholder:text-slate-400 focus:ring-2 focus:ring-brand-500 focus:outline-none",
          large ? "px-5 py-4 text-lg" : "px-3 py-2 text-sm",
        )}
      />
      {cnpjInvalido && <p className="mt-1 text-xs text-red-600">Dígito verificador do CNPJ não confere.</p>}
      {open && term.length >= 3 && (
        <ul id={listId} role="listbox" className="absolute z-[1100] mt-1 max-h-96 w-full overflow-auto rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
          {sug.isLoading && <li className="px-4 py-2 text-sm text-slate-500">Buscando…</li>}
          {!sug.isLoading && items.length === 0 && (
            <li className="px-4 py-2 text-sm text-slate-500">
              Nada encontrado. <span className="text-slate-400">Enter para busca completa.</span>
            </li>
          )}
          {items.map((it, i) => (
            <li
              key={it.key}
              role="option"
              aria-selected={i === active}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => {
                e.preventDefault();
                it.go();
                reset();
              }}
              className={cx("cursor-pointer px-4 py-2", i === active && "bg-brand-50")}
            >
              <div className="text-sm font-medium text-slate-900">{it.label}</div>
              <div className="text-xs text-slate-500">{it.sub}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
