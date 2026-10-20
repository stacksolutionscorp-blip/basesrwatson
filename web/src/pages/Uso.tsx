import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, ErrorBox, KV, PageTitle, Select, Spinner, Table, Td } from "../components/ui";
import { api } from "../lib/api";
import * as fmt from "../lib/format";
import type { Uso as UsoT } from "../lib/types";

export function UsoChart({ dias }: { dias: UsoT["dias"] }) {
  const data = dias.map((d) => ({ dia: fmt.date(d.dia).slice(0, 5), ok: d.requisicoes - d.erros, erros: d.erros }));
  return (
    <div className="h-64" data-testid="grafico-uso">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid vertical={false} stroke="#e2e8f0" />
          <XAxis dataKey="dia" tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} />
          <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} />
          <Tooltip formatter={(v, k) => [String(v), k === "ok" ? "Sucesso" : "Erros"]} />
          <Bar dataKey="ok" stackId="a" fill="#2557e6" radius={[0, 0, 0, 0]} />
          <Bar dataKey="erros" stackId="a" fill="#f59e0b" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Uso() {
  const [dias, setDias] = useState(30);
  const uso = useQuery({ queryKey: ["uso", dias], queryFn: () => api<UsoT>("/v1/uso", { query: { dias } }) });
  const total = uso.data?.dias.reduce((s, d) => s + d.requisicoes, 0) ?? 0;

  return (
    <div className="space-y-5">
      <PageTitle
        title="Uso da API"
        subtitle="Consumo da sua conta (painel e integrações ligadas a ela)."
        actions={
          <Select value={dias} onChange={(e) => setDias(Number(e.target.value))} aria-label="Período">
            <option value={7}>7 dias</option>
            <option value={30}>30 dias</option>
            <option value={90}>90 dias</option>
          </Select>
        }
      />
      {uso.isLoading && <Spinner />}
      <ErrorBox error={uso.error} />
      {uso.data && (
        <>
          <div className="grid gap-5 lg:grid-cols-3">
            <Card title="Requisições por dia" className="lg:col-span-2">
              <UsoChart dias={uso.data.dias} />
            </Card>
            <Card title={`Plano ${uso.data.plano}`}>
              <KV
                items={[
                  ["Requisições no período", fmt.integer(total)],
                  ["Por minuto", fmt.integer(uso.data.limites.req_por_minuto)],
                  ["Por dia", fmt.integer(uso.data.limites.req_por_dia)],
                  ["CNPJs por lote", fmt.integer(uso.data.limites.lote_max)],
                  ["Linhas por exportação", fmt.integer(uso.data.limites.export_max)],
                  ["CNPJs monitorados", fmt.integer(uso.data.limites.monitor_max)],
                ]}
              />
            </Card>
          </div>
          <Card title="Por rota">
            <Table head={["Rota", "Requisições"]}>
              {Object.entries(uso.data.por_rota).map(([rota, n]) => (
                <tr key={rota}>
                  <Td className="font-mono text-xs">{rota}</Td>
                  <Td>{fmt.integer(n)}</Td>
                </tr>
              ))}
            </Table>
          </Card>
        </>
      )}
    </div>
  );
}
