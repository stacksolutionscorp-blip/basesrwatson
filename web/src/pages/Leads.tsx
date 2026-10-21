import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AsyncPicker, type Option } from "../components/AsyncPicker";
import { ClusterMap, type MapPoint } from "../components/maps";
import { Badge, Button, Card, Empty, ErrorBox, Field, Input, Modal, PageTitle, Pagination, Select, Spinner, Tabs, cx } from "../components/ui";
import { API_BASE, api, del, post, put, qs } from "../lib/api";
import * as fmt from "../lib/format";
import type { Lead, LeadStatus, LeadsConfig, Lista } from "../lib/types";

const STATUS_LABEL: Record<LeadStatus, string> = {
  novo: "Novo",
  contatado: "Contatado",
  interessado: "Interessado",
  proposta: "Proposta enviada",
  fechado: "Fechado",
  sem_interesse: "Sem interesse",
};
const STATUS_TONE: Record<LeadStatus, "gray" | "blue" | "amber" | "green" | "red"> = {
  novo: "gray",
  contatado: "blue",
  interessado: "amber",
  proposta: "amber",
  fechado: "green",
  sem_interesse: "red",
};
const PORTES = [
  [1, "ME"],
  [3, "EPP"],
  [5, "Médio/grande"],
] as const;

function useDebounced<T>(value: T, ms = 400): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function ScoreBadge({ score }: { score: number }) {
  const tone = score >= 70 ? "bg-emerald-600" : score >= 45 ? "bg-amber-500" : "bg-slate-400";
  return (
    <span className={cx("inline-flex size-11 shrink-0 flex-col items-center justify-center rounded-lg text-white", tone)} title="Score do lead (0–100)">
      <span className="text-base leading-none font-semibold">{score}</span>
      <span className="text-[9px] uppercase opacity-80">score</span>
    </span>
  );
}

function LeadCard({ lead, onChanged }: { lead: Lead; onChanged: () => void }) {
  const [nota, setNota] = useState(lead.nota ?? "");
  const [aberto, setAberto] = useState(false);
  const [bloquear, setBloquear] = useState(false);
  const salvar = useMutation({
    mutationFn: (body: { status: LeadStatus; nota?: string | null }) => put(`/v1/leads/${lead.cnpj}`, body),
    onSuccess: onChanged,
  });
  const historico = useQuery({
    queryKey: ["lead-hist", lead.cnpj],
    queryFn: () => api<{ criado_em: string; status: string; nota: string | null; usuario: string | null }[]>(`/v1/leads/${lead.cnpj}/historico`),
    enabled: aberto,
  });
  const nome = lead.nome_fantasia || lead.razao_social || lead.cnpj_formatado;

  return (
    <li className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="lead">
      <div className="flex gap-3">
        <ScoreBadge score={lead.score} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Link to={`/empresa/${lead.cnpj}`} className="font-medium text-slate-900 hover:text-brand-700 hover:underline">
              {nome}
            </Link>
            {lead.status !== "novo" && <Badge tone={STATUS_TONE[lead.status]}>{STATUS_LABEL[lead.status]}</Badge>}
            {lead.porte && <Badge>{lead.porte}</Badge>}
          </div>
          <p className="text-xs text-slate-500">
            {lead.nome_fantasia && lead.razao_social ? `${lead.razao_social} · ` : ""}
            <span className="font-mono">{lead.cnpj_formatado}</span>
          </p>
          <p className="mt-1 text-sm text-slate-600">{lead.cnae_principal.descricao}</p>
          <p className="text-xs text-slate-500">
            {[lead.bairro, lead.municipio && `${lead.municipio}/${lead.uf}`].filter(Boolean).join(" · ")}
            {lead.distancia_km !== null && ` · ${lead.distancia_km.toLocaleString("pt-BR")} km`}
            {lead.idade_anos !== null && ` · ${Math.floor(lead.idade_anos)} anos de empresa`}
            {lead.capital_social !== null && Number(lead.capital_social) > 0 && ` · capital ${fmt.money(lead.capital_social)}`}
          </p>

          {lead.decisores.length > 0 && (
            <p className="mt-2 text-sm">
              <span className="text-xs font-medium text-slate-500 uppercase">Decisores: </span>
              {lead.decisores.map((d, i) => (
                <span key={i}>
                  {i > 0 && " · "}
                  <span className="font-medium text-slate-800">{d.nome}</span>
                  {d.qualificacao && <span className="text-slate-500"> ({d.qualificacao})</span>}
                </span>
              ))}
            </p>
          )}

          <div className="mt-3 flex flex-wrap gap-2">
            {lead.telefones.map((t) => (
              <span key={t.numero} className="inline-flex gap-1">
                <a href={`tel:+55${t.numero}`} className="inline-flex items-center gap-1 rounded-md bg-brand-50 px-2.5 py-1 text-sm font-medium text-brand-700 hover:bg-brand-100">
                  ☎ {fmt.phone(t.numero)}
                </a>
                {t.whatsapp && (
                  <a href={t.whatsapp} target="_blank" rel="noreferrer" className="inline-flex items-center rounded-md bg-emerald-50 px-2.5 py-1 text-sm font-medium text-emerald-700 hover:bg-emerald-100">
                    WhatsApp
                  </a>
                )}
              </span>
            ))}
            {lead.email && (
              <a href={`mailto:${lead.email}`} className="inline-flex items-center rounded-md bg-slate-100 px-2.5 py-1 text-sm text-slate-700 hover:bg-slate-200">
                ✉ {lead.email}
              </a>
            )}
            <a
              href={`https://www.google.com/search?q=${encodeURIComponent(`${nome} ${lead.municipio ?? ""}`)}`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center rounded-md px-2.5 py-1 text-sm text-slate-500 hover:bg-slate-100"
            >
              Pesquisar na web ↗
            </a>
          </div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
        <Select
          compact
          className="w-44 py-1 text-xs"
          aria-label={`Status de ${nome}`}
          value={lead.status}
          onChange={(e) => salvar.mutate({ status: e.target.value as LeadStatus, nota: nota || null })}
        >
          {(Object.keys(STATUS_LABEL) as LeadStatus[]).map((s) => (
            <option key={s} value={s}>
              {STATUS_LABEL[s]}
            </option>
          ))}
        </Select>
        <Input
          className="min-w-48 flex-1 py-1 text-xs"
          placeholder="Anotação (ex.: falar com o João na terça)"
          aria-label={`Anotação de ${nome}`}
          value={nota}
          onChange={(e) => setNota(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && salvar.mutate({ status: lead.status === "novo" ? "contatado" : lead.status, nota })}
        />
        <Button size="sm" variant="secondary" onClick={() => salvar.mutate({ status: lead.status === "novo" ? "contatado" : lead.status, nota })}>
          Salvar
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setAberto(!aberto)}>
          {aberto ? "Ocultar" : "Detalhes"}
        </Button>
        <Button size="sm" variant="danger" onClick={() => setBloquear(true)}>
          Não contatar
        </Button>
        {salvar.isPending && <span className="text-xs text-slate-400">salvando…</span>}
      </div>
      <ErrorBox error={salvar.error} />

      {aberto && (
        <div className="mt-3 grid gap-4 text-sm sm:grid-cols-2">
          <div>
            <p className="mb-1 text-xs font-medium text-slate-500 uppercase">Por que este score</p>
            <ul className="space-y-0.5">
              {lead.fatores.map((f) => (
                <li key={f.fator} className="flex justify-between gap-2 text-slate-600">
                  <span>{f.fator}</span>
                  <span className="font-medium text-slate-900">+{f.pontos}</span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-slate-500">
              {lead.endereco} {lead.cep && `· CEP ${fmt.cep(lead.cep)}`}
            </p>
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-slate-500 uppercase">Histórico</p>
            {historico.isLoading ? (
              <Spinner />
            ) : historico.data?.length ? (
              <ul className="space-y-1">
                {historico.data.map((h, i) => (
                  <li key={i} className="text-xs text-slate-600">
                    <span className="text-slate-400">{fmt.dateTime(h.criado_em)}</span> · {STATUS_LABEL[h.status as LeadStatus] ?? h.status}
                    {h.usuario && ` · ${h.usuario}`}
                    {h.nota && <div className="text-slate-800">“{h.nota}”</div>}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-slate-500">Nenhum contato registrado.</p>
            )}
          </div>
        </div>
      )}
      {bloquear && <NaoContatarModal lead={lead} onClose={() => setBloquear(false)} onDone={onChanged} />}
    </li>
  );
}

function NaoContatarModal({ lead, onClose, onDone }: { lead: Lead; onClose: () => void; onDone: () => void }) {
  const [motivo, setMotivo] = useState("");
  const [telefones, setTelefones] = useState(true);
  const salvar = useMutation({
    mutationFn: async () => {
      await post("/v1/leads/nao-contatar", { cnpj: lead.cnpj, motivo });
      if (telefones) for (const t of lead.telefones) await post("/v1/leads/nao-contatar", { telefone: t.numero, motivo });
    },
    onSuccess: () => {
      onDone();
      onClose();
    },
  });
  return (
    <Modal title="Não contatar mais" onClose={onClose}>
      <p className="text-sm text-slate-600">
        A empresa sai de todas as buscas e exportações. Use quando a pessoa pedir para não receber contato.
      </p>
      <Field label="Motivo">
        <Input value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder="ex.: pediu por telefone em 21/10" />
      </Field>
      {lead.telefones.length > 0 && (
        <label className="mt-3 flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={telefones} onChange={(e) => setTelefones(e.target.checked)} />
          Bloquear também os telefones ({lead.telefones.map((t) => fmt.phone(t.numero)).join(", ")}) em outras empresas
        </label>
      )}
      <ErrorBox error={salvar.error} />
      <div className="mt-4 text-right">
        <Button variant="danger" onClick={() => salvar.mutate()} disabled={salvar.isPending}>
          Confirmar
        </Button>
      </div>
    </Modal>
  );
}

function Prospectar({ config }: { config: LeadsConfig }) {
  const qc = useQueryClient();
  const [segmento, setSegmento] = useState<string>("");
  const [centro, setCentro] = useState(config.centro);
  const [raio, setRaio] = useState(config.raio_km);
  const [muns, setMuns] = useState<Option[]>([]);
  const [porte, setPorte] = useState<number[]>([]);
  const [capital, setCapital] = useState("");
  const [idade, setIdade] = useState("");
  const [celular, setCelular] = useState(false);
  const [email, setEmail] = useState(false);
  const [mei, setMei] = useState(true);
  const [trabalhados, setTrabalhados] = useState(false);
  const [pagina, setPagina] = useState(1);
  const [mapa, setMapa] = useState(true);

  const filtros = useDebounced({
    segmento: segmento || undefined,
    ...(muns.length ? { municipio_ibge: muns.map((m) => m.value) } : { lat: centro.lat, lng: centro.lng, raio_km: raio }),
    porte,
    capital_min: capital || undefined,
    idade_min_anos: idade || undefined,
    so_celular: celular,
    com_email: email,
    incluir_mei: mei,
    ocultar_trabalhados: !trabalhados,
  });
  useEffect(() => setPagina(1), [filtros]);
  const res = useQuery({
    queryKey: ["leads", filtros, pagina],
    queryFn: () => api<Lista<Lead>>("/v1/leads/busca", { query: { ...filtros, pagina, por_pagina: 25 } }),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["leads"] });
    qc.invalidateQueries({ queryKey: ["carteira"] });
  };
  const pontos: MapPoint[] = useMemo(
    () =>
      (res.data?.resultados ?? [])
        .filter((l) => l.lat !== null && l.lng !== null)
        .map((l) => ({ id: l.cnpj, lat: l.lat!, lng: l.lng!, title: l.nome_fantasia || l.razao_social || l.cnpj_formatado, subtitle: `score ${l.score}` })),
    [res.data],
  );
  const seg = config.segmentos.find((s) => s.id === segmento);
  const exportUrl = (formato: string) => `${API_BASE}/v1/leads/export${qs({ ...filtros, formato, limite: 2000 })}`;

  return (
    <div className="space-y-5">
      <Card>
        <div className="space-y-4">
          <Field label="Tipo de consórcio (perfil de comprador)" group>
            <div className="flex flex-wrap gap-2">
              {[{ id: "", nome: "Todos os segmentos", consorcio: "" }, ...config.segmentos].map((s) => (
                <button
                  key={s.id}
                  type="button"
                  aria-pressed={segmento === s.id}
                  onClick={() => setSegmento(s.id)}
                  className={cx(
                    "rounded-lg px-3 py-2 text-left text-sm ring-1",
                    segmento === s.id ? "bg-brand-600 text-white ring-brand-600" : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50",
                  )}
                >
                  <span className="block font-medium">{s.nome}</span>
                  {s.consorcio && <span className={cx("block text-xs", segmento === s.id ? "text-white/80" : "text-slate-500")}>{s.consorcio}</span>}
                </button>
              ))}
            </div>
            {seg && (
              <p className="mt-2 text-xs text-slate-500">
                Atividades: {seg.cnaes.map((c) => c.descricao ?? fmt.cnae(c.codigo)).join(" · ")}
              </p>
            )}
          </Field>

          <div className="grid gap-4 lg:grid-cols-3">
            <Field label={muns.length ? "Municípios" : `Raio de ${raio} km a partir de ${centro.nome}`} group>
              {!muns.length && (
                <input type="range" min={5} max={150} step={5} value={raio} onChange={(e) => setRaio(Number(e.target.value))} className="w-full accent-brand-600" aria-label="Raio em km" />
              )}
              <AsyncPicker
                path="/v1/municipios"
                placeholder="ou escolha cidades (ex.: Itupeva, Várzea Paulista)"
                selected={muns}
                onChange={setMuns}
                extraQuery={{ uf: "SP" }}
                toOption={(r) => ({ value: r.codigo_ibge as number, label: `${r.nome}/${r.uf}` })}
              />
            </Field>
            <Field label="Porte" group>
              <div className="flex flex-wrap gap-1.5">
                {PORTES.map(([v, label]) => {
                  const on = porte.includes(v);
                  return (
                    <button
                      key={v}
                      type="button"
                      aria-pressed={on}
                      onClick={() => setPorte(on ? porte.filter((p) => p !== v) : [...porte, v])}
                      className={cx("rounded-md px-2 py-1 text-xs font-medium ring-1", on ? "bg-brand-600 text-white ring-brand-600" : "bg-white text-slate-600 ring-slate-300")}
                    >
                      {label}
                    </button>
                  );
                })}
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <Input type="number" min={0} placeholder="Capital mín. (R$)" value={capital} onChange={(e) => setCapital(e.target.value)} aria-label="Capital mínimo" />
                <Input type="number" min={0} step="0.5" placeholder="Empresa há (anos)" value={idade} onChange={(e) => setIdade(e.target.value)} aria-label="Tempo mínimo de empresa" />
              </div>
            </Field>
            <Field label="Contato" group>
              <div className="space-y-1.5 text-sm text-slate-700">
                {(
                  [
                    [celular, setCelular, "Só com celular (WhatsApp)"],
                    [email, setEmail, "Só com e-mail"],
                    [mei, setMei, "Incluir MEI"],
                    [trabalhados, setTrabalhados, "Mostrar leads já trabalhados"],
                  ] as const
                ).map(([v, set, label]) => (
                  <label key={label} className="flex items-center gap-2">
                    <input type="checkbox" checked={v} onChange={(e) => set(e.target.checked)} />
                    {label}
                  </label>
                ))}
              </div>
            </Field>
          </div>
        </div>
      </Card>

      <div className="grid gap-5 xl:grid-cols-5">
        <div className={cx("space-y-3", mapa ? "xl:col-span-3" : "xl:col-span-5")}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-slate-500">{res.data ? `Melhores leads primeiro · página ${pagina}` : ""}</p>
            <div className="flex gap-2">
              <Button size="sm" variant="ghost" onClick={() => setMapa(!mapa)}>
                {mapa ? "Ocultar mapa" : "Mostrar mapa"}
              </Button>
              <a href={exportUrl("xlsx")}>
                <Button size="sm" variant="secondary">Exportar Excel</Button>
              </a>
              <a href={exportUrl("csv")}>
                <Button size="sm" variant="secondary">CSV (CRM)</Button>
              </a>
            </div>
          </div>
          {res.isLoading && <Spinner label="Buscando leads…" />}
          <ErrorBox error={res.error} />
          {res.data?.resultados.length === 0 && <Empty>Nenhum lead com esses filtros. Aumente o raio ou tire algum filtro.</Empty>}
          <ul className="space-y-3">
            {res.data?.resultados.map((l) => (
              <LeadCard key={l.cnpj} lead={l} onChanged={refresh} />
            ))}
          </ul>
          {res.data && res.data.resultados.length > 0 && <Pagination page={pagina} hasMore={res.data.paginacao.tem_mais} onChange={setPagina} />}
        </div>
        {mapa && (
          <Card className="h-fit xl:sticky xl:top-20 xl:col-span-2" title="Mapa">
            <ClusterMap
              points={pontos}
              circle={muns.length ? null : { lat: centro.lat, lng: centro.lng, km: raio }}
              onPick={(lat, lng) => setCentro({ lat, lng, nome: "ponto escolhido" })}
              height="h-[26rem]"
            />
            <p className="mt-2 text-xs text-slate-500">Clique no mapa para mudar o centro da busca.</p>
          </Card>
        )}
      </div>
    </div>
  );
}

function Carteira() {
  const qc = useQueryClient();
  const [status, setStatus] = useState<LeadStatus | "">("");
  const [pagina, setPagina] = useState(1);
  const res = useQuery({
    queryKey: ["carteira", status, pagina],
    queryFn: () => api<Lista<Lead> & { totais: Record<string, number> }>("/v1/leads/carteira", { query: { status: status || undefined, pagina } }),
  });
  const filtros: (LeadStatus | "")[] = ["", "contatado", "interessado", "proposta", "fechado", "sem_interesse"];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filtrar por status">
        {filtros.map((s) => (
          <button
            key={s}
            type="button"
            aria-pressed={status === s}
            onClick={() => {
              setStatus(s);
              setPagina(1);
            }}
            className={cx("rounded-md px-3 py-1.5 text-sm ring-1", status === s ? "bg-brand-600 text-white ring-brand-600" : "bg-white text-slate-700 ring-slate-300")}
          >
            {s ? STATUS_LABEL[s] : "Todos em andamento"} {s && res.data?.totais[s] ? `(${res.data.totais[s]})` : ""}
          </button>
        ))}
      </div>
      {res.isLoading && <Spinner />}
      <ErrorBox error={res.error} />
      {res.data?.resultados.length === 0 && <Empty>Nenhum lead nesta etapa. Mude o status de um lead na aba Prospectar.</Empty>}
      <ul className="space-y-3">
        {res.data?.resultados.map((l) => (
          <LeadCard key={l.cnpj} lead={l} onChanged={() => qc.invalidateQueries({ queryKey: ["carteira"] })} />
        ))}
      </ul>
      {res.data && res.data.resultados.length > 0 && <Pagination page={pagina} hasMore={res.data.paginacao.tem_mais} onChange={setPagina} />}
    </div>
  );
}

function NaoContatar() {
  const qc = useQueryClient();
  const lista = useQuery({
    queryKey: ["nao-contatar"],
    queryFn: () => api<{ id: number; cnpj: string | null; telefone: string | null; email: string | null; motivo: string | null; criado_em: string; usuario: string | null }[]>("/v1/leads/nao-contatar"),
  });
  const [novo, setNovo] = useState({ cnpj: "", telefone: "", email: "", motivo: "" });
  const add = useMutation({
    mutationFn: () => post("/v1/leads/nao-contatar", Object.fromEntries(Object.entries(novo).filter(([, v]) => v))),
    onSuccess: () => {
      setNovo({ cnpj: "", telefone: "", email: "", motivo: "" });
      qc.invalidateQueries({ queryKey: ["nao-contatar"] });
    },
  });
  const rm = useMutation({ mutationFn: (id: number) => del(`/v1/leads/nao-contatar/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["nao-contatar"] }) });
  return (
    <Card title="Pedidos de não contato">
      <p className="mb-4 text-sm text-slate-600">Quem está aqui nunca aparece nas buscas nem nas exportações de leads.</p>
      <form
        className="grid gap-2 sm:grid-cols-[1fr_1fr_1fr_1.4fr_auto]"
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate();
        }}
      >
        <Input placeholder="CNPJ" value={novo.cnpj} onChange={(e) => setNovo({ ...novo, cnpj: e.target.value })} aria-label="CNPJ" />
        <Input placeholder="Telefone" value={novo.telefone} onChange={(e) => setNovo({ ...novo, telefone: e.target.value })} aria-label="Telefone" />
        <Input placeholder="E-mail" value={novo.email} onChange={(e) => setNovo({ ...novo, email: e.target.value })} aria-label="E-mail" />
        <Input placeholder="Motivo" value={novo.motivo} onChange={(e) => setNovo({ ...novo, motivo: e.target.value })} aria-label="Motivo" />
        <Button type="submit">Adicionar</Button>
      </form>
      <ErrorBox error={add.error} />
      {lista.data?.length === 0 && <Empty>Lista vazia.</Empty>}
      <ul className="mt-4 divide-y divide-slate-100 text-sm">
        {lista.data?.map((n) => (
          <li key={n.id} className="flex items-center justify-between gap-3 py-2">
            <span>
              <span className="font-mono text-xs">{[n.cnpj, n.telefone && fmt.phone(n.telefone), n.email].filter(Boolean).join(" · ")}</span>
              <span className="block text-xs text-slate-500">
                {n.motivo ?? "sem motivo"} · {fmt.dateTime(n.criado_em)} {n.usuario && `· ${n.usuario}`}
              </span>
            </span>
            <Button size="sm" variant="ghost" onClick={() => rm.mutate(n.id)}>
              Remover
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function Leads() {
  const [aba, setAba] = useState<"prospectar" | "carteira" | "bloqueio">("prospectar");
  const config = useQuery({ queryKey: ["leads-config"], queryFn: () => api<LeadsConfig>("/v1/leads/config") });
  return (
    <div>
      <PageTitle
        title="Leads para consórcio"
        subtitle="Empresas ativas da região, com os contatos que elas declararam à Receita e quem decide. Os melhores leads aparecem primeiro."
      />
      <div className="mb-5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-relaxed text-amber-900">
        Telefones e e-mails são os declarados pela empresa à Receita Federal (dado público). Use para contato comercial B2B com
        a empresa; em ligações de telemarketing ativo use o prefixo <strong>0303</strong> (Anatel) e registre aqui quem pedir para
        não ser contatado.
      </div>
      <Tabs
        value={aba}
        onChange={setAba}
        tabs={[
          { id: "prospectar", label: "Prospectar" },
          { id: "carteira", label: "Minha carteira" },
          { id: "bloqueio", label: "Não contatar" },
        ]}
      />
      {config.isLoading && <Spinner />}
      <ErrorBox error={config.error} />
      {config.data && aba === "prospectar" && <Prospectar config={config.data} />}
      {aba === "carteira" && <Carteira />}
      {aba === "bloqueio" && <NaoContatar />}
    </div>
  );
}
