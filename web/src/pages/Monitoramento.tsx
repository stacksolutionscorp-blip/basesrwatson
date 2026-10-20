import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, Empty, ErrorBox, Field, Input, Modal, PageTitle, Spinner, Table, Td } from "../components/ui";
import { useAuth } from "../hooks/auth";
import { api, del, post } from "../lib/api";
import { formatCnpj } from "../lib/cnpj";
import * as fmt from "../lib/format";
import type { Alteracao, Webhook } from "../lib/types";

const TIPO = { situacao: "Situação cadastral", endereco: "Endereço", socios: "Quadro societário" };
const SITUACAO: Record<number, string> = { 1: "NULA", 2: "ATIVA", 3: "SUSPENSA", 4: "INAPTA", 8: "BAIXADA" };

function resumo(a: Alteracao): string {
  if (a.tipo === "situacao") {
    const de = (a.antes as { situacao: number }).situacao;
    const para = (a.depois as { situacao: number }).situacao;
    return `${SITUACAO[de] ?? de} → ${SITUACAO[para] ?? para}`;
  }
  if (a.tipo === "endereco") {
    const d = a.depois as Record<string, string | null>;
    return `Novo: ${[d.tipo_logradouro, d.logradouro, d.numero, d.bairro].filter(Boolean).join(" ")} — CEP ${fmt.cep(d.cep)}`;
  }
  const antes = (a.antes as { nome: string }[]).map((s) => s.nome);
  const depois = (a.depois as { nome: string }[]).map((s) => s.nome);
  const saiu = antes.filter((n) => !depois.includes(n));
  const entrou = depois.filter((n) => !antes.includes(n));
  return [entrou.length && `entrou: ${entrou.join(", ")}`, saiu.length && `saiu: ${saiu.join(", ")}`].filter(Boolean).join(" · ") || "qualificação alterada";
}

export function Historico({ itens }: { itens: Alteracao[] }) {
  if (!itens.length) return <Empty>Nenhuma alteração detectada desde o início do monitoramento.</Empty>;
  return (
    <ol className="space-y-3">
      {itens.map((a) => (
        <li key={a.id} className="flex gap-3 text-sm">
          <span className="w-20 shrink-0 text-slate-500">{a.referencia}</span>
          <div>
            <Badge tone={a.tipo === "situacao" ? "red" : a.tipo === "socios" ? "amber" : "blue"}>{TIPO[a.tipo]}</Badge>
            <span className="ml-2 text-slate-700">{resumo(a)}</span>
          </div>
        </li>
      ))}
    </ol>
  );
}

function Webhooks() {
  const qc = useQueryClient();
  const lista = useQuery({ queryKey: ["webhooks"], queryFn: () => api<Webhook[]>("/v1/webhooks") });
  const [url, setUrl] = useState("");
  const [criado, setCriado] = useState<Webhook | null>(null);
  const [teste, setTeste] = useState<string | null>(null);
  const criar = useMutation({
    mutationFn: () => post<Webhook>("/v1/webhooks", { url }),
    onSuccess: (w) => {
      setCriado(w);
      setUrl("");
      qc.invalidateQueries({ queryKey: ["webhooks"] });
    },
  });
  const remover = useMutation({ mutationFn: (id: number) => del(`/v1/webhooks/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["webhooks"] }) });
  const testar = useMutation({
    mutationFn: (id: number) => post<{ entregue: boolean; status_http: number | null; erro: string | null }>(`/v1/webhooks/${id}/teste`),
    onSuccess: (r) => setTeste(r.entregue ? `Entregue (HTTP ${r.status_http}).` : `Falhou: ${r.erro}`),
  });

  return (
    <Card title="Webhooks" actions={<span className="text-xs text-slate-500">POST JSON assinado (HMAC-SHA256) a cada alteração</span>}>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          criar.mutate();
        }}
      >
        <Input type="url" required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://seu-sistema.com.br/webhooks/cnpj" aria-label="URL do webhook" />
        <Button type="submit" disabled={criar.isPending}>
          Adicionar
        </Button>
      </form>
      <div className="mt-3 space-y-2">
        <ErrorBox error={criar.error || remover.error || testar.error} />
        {teste && <p className="rounded bg-slate-50 px-3 py-2 text-sm text-slate-700">{teste}</p>}
      </div>
      {lista.data && lista.data.length > 0 && (
        <ul className="mt-4 divide-y divide-slate-100">
          {lista.data.map((w) => (
            <li key={w.id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="truncate font-mono text-xs">{w.url}</span>
              <span className="flex shrink-0 gap-2">
                <Button size="sm" variant="secondary" onClick={() => testar.mutate(w.id)}>
                  Testar
                </Button>
                <Button size="sm" variant="danger" onClick={() => confirm("Remover este webhook?") && remover.mutate(w.id)}>
                  Remover
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {criado && (
        <Modal title="Webhook criado" onClose={() => setCriado(null)}>
          <p className="text-sm text-slate-600">Guarde o segredo abaixo — ele não será exibido novamente. Use-o para validar o header <code>X-CNPJ-Signature</code>.</p>
          <pre className="mt-3 overflow-x-auto rounded bg-slate-900 p-3 text-sm text-emerald-300">{criado.segredo}</pre>
          <div className="mt-4 text-right">
            <Button onClick={() => navigator.clipboard?.writeText(criado.segredo ?? "")}>Copiar</Button>
          </div>
        </Modal>
      )}
    </Card>
  );
}

export function Monitoramento() {
  const qc = useQueryClient();
  const { usuario } = useAuth();
  const lista = useQuery({ queryKey: ["monitor"], queryFn: () => api<{ cnpj: string; criado_em: string }[]>("/v1/monitor", { query: { por_pagina: 1000 } }) });
  const [texto, setTexto] = useState("");
  const [aberto, setAberto] = useState<string | null>(null);
  const [resultado, setResultado] = useState<string | null>(null);
  const adicionar = useMutation({
    mutationFn: () => post<{ adicionados: string[]; ja_monitorados: string[]; nao_encontrados: string[]; invalidos: string[] }>("/v1/monitor", {
      cnpjs: texto.split(/[\s,;]+/).filter(Boolean),
    }),
    onSuccess: (r) => {
      setTexto("");
      setResultado(
        [`${r.adicionados.length} adicionados`, r.ja_monitorados.length && `${r.ja_monitorados.length} já monitorados`,
         r.nao_encontrados.length && `não encontrados: ${r.nao_encontrados.map(formatCnpj).join(", ")}`,
         r.invalidos.length && `inválidos: ${r.invalidos.join(", ")}`].filter(Boolean).join(" · "), // prettier-ignore
      );
      qc.invalidateQueries({ queryKey: ["monitor"] });
    },
  });
  const remover = useMutation({ mutationFn: (c: string) => del(`/v1/monitor/${c}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["monitor"] }) });
  const historico = useQuery({ queryKey: ["historico", aberto], queryFn: () => api<Alteracao[]>(`/v1/monitor/${aberto}/historico`), enabled: !!aberto });

  return (
    <div className="space-y-5">
      <PageTitle
        title="Monitoramento"
        subtitle={`A cada atualização mensal da Receita, mudanças de situação, endereço e sócios são registradas e enviadas aos seus webhooks. Limite do plano: ${usuario?.plano.monitor_max ?? "—"} CNPJs.`}
      />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Adicionar CNPJs">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              adicionar.mutate();
            }}
            className="space-y-3"
          >
            <Field label="Um ou mais CNPJs">
              <textarea
                value={texto}
                onChange={(e) => setTexto(e.target.value)}
                rows={3}
                className="block w-full rounded-md border-0 p-2 font-mono text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-brand-500 focus:outline-none"
              />
            </Field>
            <Button type="submit" disabled={!texto.trim() || adicionar.isPending}>
              Monitorar
            </Button>
            <ErrorBox error={adicionar.error} />
            {resultado && <p className="text-sm text-slate-600">{resultado}</p>}
          </form>
        </Card>
        <Webhooks />
      </div>
      <Card title={`CNPJs monitorados (${lista.data?.length ?? 0})`}>
        {lista.isLoading && <Spinner />}
        {lista.data?.length === 0 && <Empty>Nenhum CNPJ monitorado ainda.</Empty>}
        {lista.data && lista.data.length > 0 && (
          <Table head={["CNPJ", "Desde", ""]}>
            {lista.data.map((m) => (
              <tr key={m.cnpj}>
                <Td>
                  <Link className="font-mono text-brand-700 hover:underline" to={`/empresa/${m.cnpj}`}>
                    {formatCnpj(m.cnpj)}
                  </Link>
                </Td>
                <Td>{fmt.dateTime(m.criado_em)}</Td>
                <Td className="text-right">
                  <span className="inline-flex gap-2">
                    <Button size="sm" variant="secondary" onClick={() => setAberto(m.cnpj)}>
                      Histórico
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => remover.mutate(m.cnpj)}>
                      Parar
                    </Button>
                  </span>
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      {aberto && (
        <Modal title={`Histórico — ${formatCnpj(aberto)}`} onClose={() => setAberto(null)} wide>
          {historico.isLoading ? <Spinner /> : <Historico itens={historico.data ?? []} />}
        </Modal>
      )}
    </div>
  );
}
