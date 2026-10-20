const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const num = new Intl.NumberFormat("pt-BR");

export function money(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? brl.format(n) : "—";
}

export function integer(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : num.format(v);
}

/** "2015-03-10" → "10/03/2015" sem passar por Date (evita deslocamento de fuso). */
export function date(v: string | null | undefined): string {
  if (!v) return "—";
  const [y, m, d] = v.slice(0, 10).split("-");
  return d && m && y ? `${d}/${m}/${y}` : v;
}

export function dateTime(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString("pt-BR");
}

export function phone(v: string): string {
  const d = v.replace(/\D/g, "");
  if (d.length === 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  if (d.length === 11) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  return v;
}

export function cep(v: string | null | undefined): string {
  if (!v) return "—";
  const d = v.replace(/\D/g, "");
  return d.length === 8 ? `${d.slice(0, 5)}-${d.slice(5)}` : v;
}

export function cnae(codigo: number | null | undefined): string {
  if (codigo === null || codigo === undefined) return "—";
  const s = String(codigo).padStart(7, "0");
  return `${s.slice(0, 4)}-${s.slice(4, 5)}/${s.slice(5)}`;
}

export function endereco(e: {
  tipo_logradouro: string | null;
  logradouro: string | null;
  numero: string | null;
  complemento: string | null;
  bairro: string | null;
}): string {
  const rua = [e.tipo_logradouro, e.logradouro].filter(Boolean).join(" ");
  return [rua, e.numero || "S/N", e.complemento, e.bairro].filter(Boolean).join(", ");
}
