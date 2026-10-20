import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { PointMap } from "../components/maps";
import { Badge, Button, Card, Empty, ErrorBox, KV, PageTitle, SituacaoBadge, Spinner, Table, Td, cx } from "../components/ui";
import { ApiError, api, del, post } from "../lib/api";
import { cleanCnpj, formatCnpj, isValidCnpj } from "../lib/cnpj";
import * as fmt from "../lib/format";
import type { Alteracao, EstabelecimentoResumo, Lista, Perfil, ScoreRisco } from "../lib/types";
import { Historico } from "./Monitoramento";

function RiskCard({ risco }: { risco: ScoreRisco }) {
  const color = risco.nivel === "alto" ? "bg-red-500" : risco.nivel === "medio" ? "bg-amber-500" : "bg-emerald-500";
  return (
    <Card title="Score de risco">
      <div className="flex items-end gap-2">
        <span className="text-3xl font-semibold text-slate-900">{risco.score}</span>
        <span className="pb-1 text-sm text-slate-500">/ 100 · {risco.nivel === "medio" ? "médio" : risco.nivel}</span>
      </div>
      <div className="mt-3 h-2 rounded-full bg-slate-100" role="meter" aria-valuenow={risco.score} aria-valuemin={0} aria-valuemax={100} aria-label="Score de risco">
        <div className={cx("h-2 rounded-full", color)} style={{ width: `${Math.max(risco.score, 3)}%` }} />
      </div>
      {risco.fatores.length ? (
        <ul className="mt-4 space-y-1.5 text-sm">
          {risco.fatores.map((f) => (
            <li key={f.fator} className="flex justify-between gap-3">
              <span className="text-slate-600">{f.fator}</span>
              <span className="font-medium text-slate-900">+{f.pontos}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-sm text-slate-500">Nenhum fator de risco identificado.</p>
      )}
    </Card>
  );
}

function MonitorButton({ cnpj }: { cnpj: string }) {
  const qc = useQueryClient();
  const lista = useQuery({ queryKey: ["monitor"], queryFn: () => api<{ cnpj: string }[]>("/v1/monitor", { query: { por_pagina: 1000 } }) });
  const monitorado = lista.data?.some((m) => m.cnpj === cnpj);
  const toggle = useMutation({
    mutationFn: () => (monitorado ? del(`/v1/monitor/${cnpj}`) : post("/v1/monitor", { cnpjs: [cnpj] })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["monitor"] }),
  });
  return (
    <Button variant={monitorado ? "secondary" : "primary"} onClick={() => toggle.mutate()} disabled={toggle.isPending || lista.isLoading}>
      {monitorado ? "✓ Monitorando" : "Monitorar"}
    </Button>
  );
}

export function Empresa() {
  const { cnpj = "" } = useParams();
  const c = cleanCnpj(cnpj);
  const valido = isValidCnpj(c);
  const perfil = useQuery({ queryKey: ["cnpj", c], queryFn: () => api<Perfil>(`/v1/cnpj/${c}`), enabled: valido, retry: false });
  const filiais = useQuery({
    queryKey: ["filiais", c.slice(0, 8)],
    queryFn: () => api<Lista<EstabelecimentoResumo>>(`/v1/cnpj/${c}/filiais`, { query: { por_pagina: 100 } }),
    enabled: valido && (perfil.data?.qtd_estabelecimentos ?? 0) > 1,
  });
  const monitor = useQuery({ queryKey: ["monitor"], queryFn: () => api<{ cnpj: string }[]>("/v1/monitor", { query: { por_pagina: 1000 } }) });
  const historico = useQuery({
    queryKey: ["historico", c],
    queryFn: () => api<Alteracao[]>(`/v1/monitor/${c}/historico`),
    enabled: !!monitor.data?.some((m) => m.cnpj === c),
  });

  if (!valido) return <ErrorBox error={`CNPJ inválido: ${cnpj}`} />;
  if (perfil.isLoading) return <Spinner />;
  if (perfil.error) {
    const naoExiste = perfil.error instanceof ApiError && perfil.error.status === 404;
    return <ErrorBox error={naoExiste ? `CNPJ ${formatCnpj(c)} não encontrado na base da Receita.` : perfil.error} />;
  }
  const p = perfil.data!;
  const e = p.endereco;

  return (
    <div className="space-y-5">
      <PageTitle
        title={p.razao_social ?? p.nome_fantasia ?? p.cnpj_formatado}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono">{p.cnpj_formatado}</span>
            <SituacaoBadge situacao={p.situacao.descricao} />
            <Badge tone="blue">{p.matriz ? "Matriz" : "Filial"}</Badge>
            {p.simples?.mei && <Badge tone="gray">MEI</Badge>}
            {p.nome_fantasia && p.razao_social && <span>· {p.nome_fantasia}</span>}
          </span>
        }
        actions={
          <>
            <Link to={`/grafo/${p.cnpj}`}>
              <Button variant="secondary">Rede societária</Button>
            </Link>
            <MonitorButton cnpj={p.cnpj} />
          </>
        }
      />

      <div className="grid gap-5 lg:grid-cols-3">
        <Card title="Dados cadastrais" className="lg:col-span-2">
          <KV
            items={[
              ["Natureza jurídica", p.natureza_juridica?.descricao],
              ["Porte", p.porte?.descricao],
              ["Capital social", fmt.money(p.capital_social)],
              ["Abertura", p.data_inicio ? `${fmt.date(p.data_inicio)} (${p.idade_anos} anos)` : "—"],
              ["Situação", `${p.situacao.descricao ?? "—"} desde ${fmt.date(p.situacao.data)}`],
              ["Motivo da situação", p.situacao.motivo?.descricao],
              ["Simples Nacional", p.simples ? (p.simples.optante ? `Optante desde ${fmt.date(p.simples.data_opcao)}` : "Não optante") : "—"],
              ["MEI", p.simples ? (p.simples.mei ? `Sim, desde ${fmt.date(p.simples.data_opcao_mei)}` : "Não") : "—"],
              ...(p.situacao_especial ? ([["Situação especial", `${p.situacao_especial} (${fmt.date(p.data_situacao_especial)})`]] as [string, string][]) : []),
              ["Estabelecimentos", fmt.integer(p.qtd_estabelecimentos)],
            ]}
          />
        </Card>
        <RiskCard risco={p.score_risco} />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Endereço e contato">
          <KV
            items={[
              ["Endereço", fmt.endereco(e)],
              ["Município", e.municipio.nome ? `${e.municipio.nome} / ${e.uf}` : e.cidade_exterior ?? "—"],
              ["CEP", fmt.cep(e.cep)],
              ["Telefones", p.contato.telefones.length ? p.contato.telefones.map(fmt.phone).join(" · ") : "—"],
              ["E-mail", p.contato.email],
            ]}
          />
        </Card>
        <Card title="Localização" actions={e.geo_precisao && <Badge>{e.geo_precisao === "municipio" ? "aprox. (município)" : `precisão: ${e.geo_precisao}`}</Badge>}>
          {e.lat !== null && e.lng !== null ? (
            <PointMap lat={e.lat} lng={e.lng} label={p.razao_social ?? p.cnpj_formatado} precisao={e.geo_precisao} />
          ) : (
            <Empty>Sem coordenadas para este endereço.</Empty>
          )}
        </Card>
      </div>

      <Card title="Atividades (CNAE)">
        <ul className="space-y-1.5 text-sm">
          <li>
            <span className="font-mono text-slate-500">{fmt.cnae(p.cnae_principal?.codigo)}</span>{" "}
            <span className="font-medium text-slate-900">{p.cnae_principal?.descricao}</span> <Badge tone="blue">principal</Badge>
          </li>
          {p.cnaes_secundarios.map((s) => (
            <li key={s.codigo}>
              <span className="font-mono text-slate-500">{fmt.cnae(s.codigo)}</span> {s.descricao}
            </li>
          ))}
        </ul>
      </Card>

      <Card title={`Quadro societário (${p.socios.length})`}>
        {p.socios.length === 0 ? (
          <Empty>Nenhum sócio informado.</Empty>
        ) : (
          <Table head={["Nome", "CPF/CNPJ", "Qualificação", "Entrada", "Faixa etária"]}>
            {p.socios.map((s, i) => (
              <tr key={i}>
                <Td>
                  {s.tipo === "PJ" && s.cpf_cnpj && s.cpf_cnpj.length === 14 ? (
                    <Link className="font-medium text-brand-700 hover:underline" to={`/empresa/${s.cpf_cnpj}`}>
                      {s.nome}
                    </Link>
                  ) : (
                    <Link className="font-medium text-brand-700 hover:underline" to={`/socios?nome=${encodeURIComponent(s.nome ?? "")}`}>
                      {s.nome}
                    </Link>
                  )}
                  {s.representante?.nome && <div className="text-xs text-slate-500">Repr.: {s.representante.nome} ({s.representante.qualificacao?.descricao})</div>}
                </Td>
                <Td className="font-mono text-xs">{s.cpf_cnpj ?? "—"}</Td>
                <Td>{s.qualificacao?.descricao}</Td>
                <Td>{fmt.date(s.data_entrada)}</Td>
                <Td>{s.faixa_etaria ?? "—"}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {p.qtd_estabelecimentos > 1 && (
        <Card title={`Estabelecimentos (${p.qtd_estabelecimentos})`}>
          {filiais.isLoading && <Spinner />}
          <ErrorBox error={filiais.error} />
          {filiais.data && (
            <Table head={["CNPJ", "Tipo", "Nome fantasia", "Situação", "Município"]}>
              {filiais.data.resultados.map((f) => (
                <tr key={f.cnpj} className={f.cnpj === p.cnpj ? "bg-brand-50/50" : undefined}>
                  <Td>
                    <Link className="font-mono text-brand-700 hover:underline" to={`/empresa/${f.cnpj}`}>
                      {f.cnpj_formatado}
                    </Link>
                  </Td>
                  <Td>{f.matriz ? "Matriz" : "Filial"}</Td>
                  <Td>{f.nome_fantasia ?? "—"}</Td>
                  <Td>
                    <SituacaoBadge situacao={f.situacao} />
                  </Td>
                  <Td>{f.municipio ? `${f.municipio}/${f.uf}` : "—"}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      )}

      {historico.data && (
        <Card title="Histórico de alterações (monitoramento)">
          <Historico itens={historico.data} />
        </Card>
      )}

      <p className="text-xs text-slate-400">Base da Receita Federal: {p.referencia}. Os dados refletem a última publicação mensal.</p>
    </div>
  );
}
