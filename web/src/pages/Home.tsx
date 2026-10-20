import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { SearchBox } from "../components/SearchBox";
import { useAuth } from "../hooks/auth";
import { api } from "../lib/api";

const ATALHOS = [
  { to: "/busca", titulo: "Busca avançada", texto: "CNAE, região, raio em km, porte, capital, abertura e Simples/MEI — com mapa e exportação." },
  { to: "/socios", titulo: "Sócios", texto: "Encontre uma pessoa ou empresa sócia e todas as empresas ligadas a ela." },
  { to: "/lote", titulo: "Consulta em lote", texto: "Cole até centenas de CNPJs e baixe o resultado em planilha." },
  { to: "/monitoramento", titulo: "Monitoramento", texto: "Acompanhe mudanças de situação, endereço e sócios, com alertas por webhook." },
];

export function Home() {
  const { usuario } = useAuth();
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<{ referencia: string | null }>("/health") });
  const ref = health.data?.referencia;

  return (
    <div className="mx-auto max-w-3xl pt-6">
      <h1 className="text-2xl font-semibold text-slate-900">Olá, {usuario?.nome?.split(" ")[0]}</h1>
      <p className="mt-1 text-slate-500">
        Consulte empresas brasileiras pela base pública da Receita Federal
        {ref && (
          <>
            {" "}
            — base de <strong className="text-slate-700">{ref}</strong>
          </>
        )}
        .
      </p>
      <div className="mt-6">
        <SearchBox large autoFocus />
        <p className="mt-2 text-xs text-slate-400">Ex.: 11.222.333/0001-81 · padaria são joão · nome do sócio</p>
      </div>
      {health.data && ref === null && (
        <div className="mt-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          A base da Receita ainda não foi carregada. Rode <code>cnpj-etl run</code> (base real) ou <code>cnpj-etl demo</code>.
        </div>
      )}
      <div className="mt-10 grid gap-4 sm:grid-cols-2">
        {ATALHOS.map((a) => (
          <Link key={a.to} to={a.to} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-brand-500/40 hover:shadow">
            <h2 className="font-medium text-slate-900">{a.titulo}</h2>
            <p className="mt-1 text-sm text-slate-500">{a.texto}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
