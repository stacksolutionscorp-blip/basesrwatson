import { useQuery } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AsyncPicker, type Option } from "../components/AsyncPicker";
import { ClusterMap, type MapPoint } from "../components/maps";
import { Button, Card, Empty, ErrorBox, Field, Input, PageTitle, Pagination, Select, SituacaoBadge, Spinner, Table, Td, cx } from "../components/ui";
import { API_BASE, api, qs } from "../lib/api";
import * as fmt from "../lib/format";
import type { EstabelecimentoResumo, Lista } from "../lib/types";

const UFS = "AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split(" ");
const SITUACOES = [
  [2, "Ativa"],
  [3, "Suspensa"],
  [4, "Inapta"],
  [8, "Baixada"],
  [1, "Nula"],
] as const;
const PORTES = [
  [1, "ME"],
  [3, "EPP"],
  [5, "Demais"],
  [0, "Não informado"],
] as const;
const LIST_KEYS = ["cnae", "uf", "municipio_ibge", "situacao", "porte"] as const;
const SCALAR_KEYS = ["q", "lat", "lng", "raio_km", "capital_min", "capital_max", "abertura_de", "abertura_ate", "simples", "mei", "matriz", "somente_cnae_principal"] as const;

type Filters = Record<(typeof LIST_KEYS)[number], string[]> & Record<(typeof SCALAR_KEYS)[number], string>;

function fromParams(sp: URLSearchParams): Filters {
  const f = {} as Filters;
  LIST_KEYS.forEach((k) => (f[k] = sp.getAll(k)));
  SCALAR_KEYS.forEach((k) => (f[k] = sp.get(k) ?? ""));
  return f;
}

function toQuery(f: Filters): Record<string, string | string[]> {
  const out: Record<string, string | string[]> = {};
  for (const [k, v] of Object.entries(f)) if ((Array.isArray(v) && v.length) || (!Array.isArray(v) && v)) out[k] = v;
  return out;
}

function Chips<T extends string | number>({ options, value, onChange }: { options: readonly (readonly [T, string])[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map(([v, label]) => {
        const on = value.includes(String(v));
        return (
          <button
            type="button"
            key={String(v)}
            aria-pressed={on}
            onClick={() => onChange(on ? value.filter((x) => x !== String(v)) : [...value, String(v)])}
            className={cx("rounded-md px-2 py-1 text-xs font-medium ring-1", on ? "bg-brand-600 text-white ring-brand-600" : "bg-white text-slate-600 ring-slate-300 hover:bg-slate-50")}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

export function Busca() {
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const aplicado = useMemo(() => fromParams(sp), [sp]);
  const pagina = Number(sp.get("pagina") ?? 1);
  const [f, setF] = useState<Filters>(aplicado);
  const [cnaes, setCnaes] = useState<Option[]>(aplicado.cnae.map((c) => ({ value: Number(c), label: fmt.cnae(Number(c)) })));
  const [muns, setMuns] = useState<Option[]>(aplicado.municipio_ibge.map((m) => ({ value: Number(m), label: m })));
  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => setF((old) => ({ ...old, [k]: v }));

  const temFiltro = sp.toString().replace(/pagina=\d+&?/, "").length > 0;
  const query = { ...toQuery(aplicado), pagina, por_pagina: 50 };
  const res = useQuery({
    queryKey: ["busca", query],
    queryFn: () => api<Lista<EstabelecimentoResumo>>("/v1/busca", { query }),
    enabled: temFiltro,
  });

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const next = { ...f, cnae: cnaes.map((c) => String(c.value)), municipio_ibge: muns.map((m) => String(m.value)) };
    setSp(new URLSearchParams(qs(toQuery(next)).slice(1)));
  };
  const limpar = () => {
    setF(fromParams(new URLSearchParams()));
    setCnaes([]);
    setMuns([]);
    setSp(new URLSearchParams());
  };
  const minhaLocalizacao = () =>
    navigator.geolocation?.getCurrentPosition((pos) => {
      setF((old) => ({ ...old, lat: pos.coords.latitude.toFixed(5), lng: pos.coords.longitude.toFixed(5), raio_km: old.raio_km || "10" }));
    });

  const pontos: MapPoint[] = useMemo(
    () =>
      (res.data?.resultados ?? [])
        .filter((r) => r.lat !== null && r.lng !== null)
        .map((r) => ({
          id: r.cnpj,
          lat: r.lat!,
          lng: r.lng!,
          title: r.razao_social ?? r.nome_fantasia ?? r.cnpj_formatado,
          subtitle: `${r.cnpj_formatado} · ${r.municipio ?? ""}/${r.uf ?? ""}`,
          color: r.situacao === "ATIVA" ? "#2557e6" : "#94a3b8",
        })),
    [res.data],
  );
  const circulo = f.lat && f.lng && f.raio_km ? { lat: Number(f.lat), lng: Number(f.lng), km: Number(f.raio_km) } : null;
  const exportUrl = (formato: string) => `${API_BASE}/v1/export${qs({ ...toQuery(aplicado), formato })}`;

  return (
    <div className="space-y-5">
      <PageTitle title="Busca avançada" subtitle="Combine filtros; clique no mapa para buscar num raio a partir de um ponto." />
      <form onSubmit={submit}>
        <Card>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <Field label="Texto (razão social, nome fantasia ou CNPJ)">
              <Input value={f.q} onChange={(e) => set("q", e.target.value)} placeholder="ex.: transportes" />
            </Field>
            <Field label="CNAE" group>
              <AsyncPicker
                path="/v1/cnaes"
                placeholder="código ou descrição"
                selected={cnaes}
                onChange={setCnaes}
                toOption={(r) => ({ value: r.codigo as number, label: `${fmt.cnae(r.codigo as number)} ${String(r.descricao).slice(0, 40)}` })}
              />
              <label className="mt-1 flex items-center gap-1.5 text-xs text-slate-500">
                <input type="checkbox" checked={f.somente_cnae_principal === "true"} onChange={(e) => set("somente_cnae_principal", e.target.checked ? "true" : "")} />
                só atividade principal
              </label>
            </Field>
            <Field label="Município" group>
              <AsyncPicker
                path="/v1/municipios"
                placeholder="nome da cidade"
                selected={muns}
                onChange={setMuns}
                toOption={(r) => ({ value: r.codigo_ibge as number, label: `${r.nome}/${r.uf}` })}
              />
            </Field>
            <div className="md:col-span-2 xl:col-span-3">
              <Field label="UF" group>
                <Chips options={UFS.map((u) => [u, u] as const)} value={f.uf} onChange={(v) => set("uf", v)} />
              </Field>
            </div>
            <Field label="Situação cadastral" group>
              <Chips options={SITUACOES} value={f.situacao} onChange={(v) => set("situacao", v)} />
            </Field>
            <Field label="Porte" group>
              <Chips options={PORTES} value={f.porte} onChange={(v) => set("porte", v)} />
            </Field>
            <div className="grid grid-cols-3 gap-2">
              {(["simples", "mei", "matriz"] as const).map((k) => (
                <Field key={k} label={k === "simples" ? "Simples" : k === "mei" ? "MEI" : "Tipo"}>
                  <Select value={f[k]} onChange={(e) => set(k, e.target.value)} compact>
                    <option value="">Todos</option>
                    <option value="true">{k === "matriz" ? "Matriz" : "Sim"}</option>
                    <option value="false">{k === "matriz" ? "Filial" : "Não"}</option>
                  </Select>
                </Field>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Capital mínimo (R$)">
                <Input type="number" min={0} value={f.capital_min} onChange={(e) => set("capital_min", e.target.value)} />
              </Field>
              <Field label="Capital máximo (R$)">
                <Input type="number" min={0} value={f.capital_max} onChange={(e) => set("capital_max", e.target.value)} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Aberta a partir de">
                <Input type="date" value={f.abertura_de} onChange={(e) => set("abertura_de", e.target.value)} />
              </Field>
              <Field label="Aberta até">
                <Input type="date" value={f.abertura_ate} onChange={(e) => set("abertura_ate", e.target.value)} />
              </Field>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <Field label="Latitude">
                <Input value={f.lat} onChange={(e) => set("lat", e.target.value)} placeholder="-23.55" />
              </Field>
              <Field label="Longitude">
                <Input value={f.lng} onChange={(e) => set("lng", e.target.value)} placeholder="-46.63" />
              </Field>
              <Field label="Raio (km)">
                <Input type="number" min={0.1} max={200} step="any" value={f.raio_km} onChange={(e) => set("raio_km", e.target.value)} />
              </Field>
            </div>
          </div>
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <Button type="submit">Buscar</Button>
            <Button variant="ghost" onClick={limpar}>
              Limpar
            </Button>
            <Button variant="ghost" onClick={minhaLocalizacao}>
              Usar minha localização
            </Button>
            {circulo && (
              <Button variant="ghost" onClick={() => setF((o) => ({ ...o, lat: "", lng: "", raio_km: "" }))}>
                Remover raio
              </Button>
            )}
          </div>
        </Card>
      </form>

      <div className="grid gap-5 xl:grid-cols-5">
        <Card
          className="xl:col-span-3"
          title="Resultados"
          actions={
            temFiltro && (
              <div className="flex gap-2">
                <a href={exportUrl("csv")}>
                  <Button variant="secondary" size="sm">CSV</Button>
                </a>
                <a href={exportUrl("xlsx")}>
                  <Button variant="secondary" size="sm">Excel</Button>
                </a>
              </div>
            )
          }
        >
          {!temFiltro && <Empty>Defina ao menos um filtro e clique em Buscar.</Empty>}
          {res.isFetching && <Spinner />}
          <ErrorBox error={res.error} />
          {res.data && res.data.resultados.length === 0 && <Empty>Nenhuma empresa encontrada com esses filtros.</Empty>}
          {res.data && res.data.resultados.length > 0 && (
            <>
              <Table head={["Empresa", "Situação", "Município", "Capital", circulo ? "Distância" : "Abertura"]}>
                {res.data.resultados.map((r) => (
                  <tr key={r.cnpj}>
                    <Td>
                      <Link to={`/empresa/${r.cnpj}`} className="font-medium text-brand-700 hover:underline">
                        {r.razao_social ?? r.nome_fantasia}
                      </Link>
                      <div className="font-mono text-xs whitespace-nowrap text-slate-500">
                        {r.cnpj_formatado} {r.matriz === false && "· filial"}
                      </div>
                      {r.nome_fantasia && <div className="text-xs text-slate-500">{r.nome_fantasia}</div>}
                    </Td>
                    <Td>
                      <SituacaoBadge situacao={r.situacao} />
                    </Td>
                    <Td className="whitespace-nowrap">{r.municipio ? `${r.municipio}/${r.uf}` : "—"}</Td>
                    <Td className="whitespace-nowrap">{fmt.money(r.capital_social)}</Td>
                    <Td className="whitespace-nowrap">{circulo ? `${r.distancia_km?.toLocaleString("pt-BR")} km` : fmt.date(r.data_inicio)}</Td>
                  </tr>
                ))}
              </Table>
              <Pagination
                page={pagina}
                hasMore={res.data.paginacao.tem_mais}
                onChange={(p) => {
                  const next = new URLSearchParams(sp);
                  next.set("pagina", String(p));
                  setSp(next);
                }}
              />
            </>
          )}
        </Card>
        <Card className="xl:col-span-2" title="Mapa">
          <ClusterMap
            points={pontos}
            circle={circulo}
            onPick={(lat, lng) => setF((o) => ({ ...o, lat: lat.toFixed(5), lng: lng.toFixed(5), raio_km: o.raio_km || "5" }))}
            onOpen={(p) => navigate(`/empresa/${p.id}`)}
          />
          <p className="mt-2 text-xs text-slate-500">
            Clique no mapa para definir o centro do raio. Empresas ainda não geocodificadas aparecem no centro do município.
          </p>
        </Card>
      </div>
    </div>
  );
}
