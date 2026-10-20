import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Badge, Button, Card, Empty, ErrorBox, Field, Input, Modal, PageTitle, Select, Spinner, Table, Tabs, Td } from "../components/ui";
import { api, patch, post, put } from "../lib/api";
import * as fmt from "../lib/format";

type Aba = "usuarios" | "chaves" | "planos" | "etl" | "webhooks" | "uso" | "auditoria";

interface Plano {
  id: string;
  nome: string;
  req_por_minuto: number;
  req_por_dia: number;
  lote_max: number;
  export_max: number;
  monitor_max: number;
}

const usePlanos = () => useQuery({ queryKey: ["admin", "planos"], queryFn: () => api<Plano[]>("/v1/admin/planos") });

function Usuarios() {
  const qc = useQueryClient();
  const planos = usePlanos();
  const lista = useQuery({
    queryKey: ["admin", "usuarios"],
    queryFn: () =>
      api<{ id: number; email: string; nome: string; papel: string; ativo: boolean; plano: string; termos_versao: string | null; ultimo_login_em: string | null }[]>(
        "/v1/admin/usuarios",
      ),
  });
  const [novo, setNovo] = useState({ email: "", nome: "", senha: "", papel: "usuario", plano: "pro" });
  const [aberto, setAberto] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ["admin", "usuarios"] });
  const criar = useMutation({
    mutationFn: () => post("/v1/admin/usuarios", novo),
    onSuccess: () => {
      setAberto(false);
      setNovo({ email: "", nome: "", senha: "", papel: "usuario", plano: "pro" });
      refresh();
    },
  });
  const alterar = useMutation({ mutationFn: ({ id, ...body }: { id: number } & Record<string, unknown>) => patch(`/v1/admin/usuarios/${id}`, body), onSuccess: refresh });

  return (
    <Card title="Usuários do painel" actions={<Button size="sm" onClick={() => setAberto(true)}>Novo usuário</Button>}>
      <ErrorBox error={alterar.error} />
      {lista.isLoading && <Spinner />}
      {lista.data && (
        <Table head={["Usuário", "Papel", "Plano", "Termos", "Último acesso", ""]}>
          {lista.data.map((u) => (
            <tr key={u.id} className={u.ativo ? undefined : "opacity-50"}>
              <Td>
                <div className="font-medium text-slate-900">{u.nome}</div>
                <div className="text-xs text-slate-500">{u.email}</div>
              </Td>
              <Td>
                <Badge tone={u.papel === "admin" ? "blue" : "gray"}>{u.papel}</Badge>
              </Td>
              <Td>
                <Select value={u.plano} onChange={(e) => alterar.mutate({ id: u.id, plano: e.target.value })} aria-label="Plano" compact className="py-1 text-xs">
                  {planos.data?.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.nome}
                    </option>
                  ))}
                </Select>
              </Td>
              <Td className="text-xs">{u.termos_versao ?? "pendente"}</Td>
              <Td className="text-xs">{fmt.dateTime(u.ultimo_login_em)}</Td>
              <Td className="text-right">
                <span className="inline-flex gap-2">
                  <Button size="sm" variant="secondary" onClick={() => alterar.mutate({ id: u.id, papel: u.papel === "admin" ? "usuario" : "admin" })}>
                    {u.papel === "admin" ? "Tornar usuário" : "Tornar admin"}
                  </Button>
                  <Button size="sm" variant={u.ativo ? "danger" : "secondary"} onClick={() => alterar.mutate({ id: u.id, ativo: !u.ativo })}>
                    {u.ativo ? "Desativar" : "Reativar"}
                  </Button>
                </span>
              </Td>
            </tr>
          ))}
        </Table>
      )}
      {aberto && (
        <Modal title="Novo usuário" onClose={() => setAberto(false)}>
          <form
            className="space-y-3"
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              criar.mutate();
            }}
          >
            <Field label="Nome">
              <Input required value={novo.nome} onChange={(e) => setNovo({ ...novo, nome: e.target.value })} />
            </Field>
            <Field label="E-mail">
              <Input type="email" required value={novo.email} onChange={(e) => setNovo({ ...novo, email: e.target.value })} />
            </Field>
            <Field label="Senha inicial" hint="Mínimo de 10 caracteres, misturando letras e números ou símbolos">
              <Input type="password" required minLength={10} value={novo.senha} onChange={(e) => setNovo({ ...novo, senha: e.target.value })} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Papel">
                <Select value={novo.papel} onChange={(e) => setNovo({ ...novo, papel: e.target.value })}>
                  <option value="usuario">Usuário</option>
                  <option value="admin">Administrador</option>
                </Select>
              </Field>
              <Field label="Plano">
                <Select value={novo.plano} onChange={(e) => setNovo({ ...novo, plano: e.target.value })}>
                  {planos.data?.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.nome}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <ErrorBox error={criar.error} />
            <div className="text-right">
              <Button type="submit" disabled={criar.isPending}>
                Criar
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </Card>
  );
}

function Chaves() {
  const qc = useQueryClient();
  const planos = usePlanos();
  const lista = useQuery({
    queryKey: ["admin", "chaves"],
    queryFn: () =>
      api<{ id: number; nome: string; prefixo: string; plano: string; ativo: boolean; criado_em: string; usuario_email: string | null; ultimo_uso_em: string | null }[]>(
        "/v1/admin/chaves",
      ),
  });
  const [nome, setNome] = useState("");
  const [plano, setPlano] = useState("pro");
  const [criada, setCriada] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["admin", "chaves"] });
  const criar = useMutation({
    mutationFn: () => post<{ chave: string }>("/v1/admin/chaves", { nome, plano }),
    onSuccess: (r) => {
      setCriada(r.chave);
      setNome("");
      refresh();
    },
  });
  const alterar = useMutation({ mutationFn: ({ id, ...b }: { id: number } & Record<string, unknown>) => patch(`/v1/admin/chaves/${id}`, b), onSuccess: refresh });

  return (
    <Card title="Chaves de API (integrações)">
      <form
        className="mb-4 grid gap-2 sm:grid-cols-[1fr_10rem_auto]"
        onSubmit={(e) => {
          e.preventDefault();
          criar.mutate();
        }}
      >
        <Input required placeholder="Nome do sistema/cliente, ex.: ERP financeiro" value={nome} onChange={(e) => setNome(e.target.value)} aria-label="Nome da chave" />
        <Select value={plano} onChange={(e) => setPlano(e.target.value)} aria-label="Plano">
          {planos.data?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.nome}
            </option>
          ))}
        </Select>
        <Button type="submit">Gerar chave</Button>
      </form>
      <ErrorBox error={criar.error || alterar.error} />
      {lista.data?.length === 0 && <Empty>Nenhuma chave de integração.</Empty>}
      {lista.data && lista.data.length > 0 && (
        <Table head={["Nome", "Prefixo", "Plano", "Último uso", ""]}>
          {lista.data.map((k) => (
            <tr key={k.id} className={k.ativo ? undefined : "opacity-50"}>
              <Td>
                {k.nome}
                {!k.ativo && <Badge tone="red">revogada</Badge>}
              </Td>
              <Td className="font-mono text-xs">{k.prefixo}…</Td>
              <Td>
                <Select value={k.plano} onChange={(e) => alterar.mutate({ id: k.id, plano: e.target.value })} aria-label="Plano da chave" compact className="py-1 text-xs">
                  {planos.data?.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.nome}
                    </option>
                  ))}
                </Select>
              </Td>
              <Td className="text-xs">{fmt.dateTime(k.ultimo_uso_em)}</Td>
              <Td className="text-right">
                <Button size="sm" variant={k.ativo ? "danger" : "secondary"} onClick={() => alterar.mutate({ id: k.id, ativo: !k.ativo })}>
                  {k.ativo ? "Revogar" : "Reativar"}
                </Button>
              </Td>
            </tr>
          ))}
        </Table>
      )}
      {criada && (
        <Modal title="Chave criada" onClose={() => setCriada(null)}>
          <p className="text-sm text-slate-600">Copie agora: a chave não será exibida novamente. Envie no header <code>X-API-Key</code>.</p>
          <pre className="mt-3 overflow-x-auto rounded bg-slate-900 p-3 text-sm text-emerald-300" data-testid="chave-criada">{criada}</pre>
          <div className="mt-4 text-right">
            <Button onClick={() => navigator.clipboard?.writeText(criada)}>Copiar</Button>
          </div>
        </Modal>
      )}
    </Card>
  );
}

function Planos() {
  const qc = useQueryClient();
  const planos = usePlanos();
  const [edit, setEdit] = useState<Plano | null>(null);
  const salvar = useMutation({
    mutationFn: (p: Plano) => {
      const { id, ...body } = p;
      return put(`/v1/admin/planos/${id}`, body);
    },
    onSuccess: () => {
      setEdit(null);
      qc.invalidateQueries({ queryKey: ["admin", "planos"] });
    },
  });
  const campos: [keyof Plano, string][] = [
    ["req_por_minuto", "Req./minuto"],
    ["req_por_dia", "Req./dia"],
    ["lote_max", "CNPJs por lote (máx. 500)"],
    ["export_max", "Linhas por exportação"],
    ["monitor_max", "CNPJs monitorados"],
  ];
  return (
    <Card title="Planos" actions={<Button size="sm" onClick={() => setEdit({ id: "", nome: "", req_por_minuto: 60, req_por_dia: 10000, lote_max: 100, export_max: 10000, monitor_max: 100 })}>Novo plano</Button>}>
      {planos.data && (
        <Table head={["Plano", ...campos.map((c) => c[1]), ""]}>
          {planos.data.map((p) => (
            <tr key={p.id}>
              <Td>
                {p.nome} <span className="text-xs text-slate-400">({p.id})</span>
              </Td>
              {campos.map(([k]) => (
                <Td key={k}>{fmt.integer(p[k] as number)}</Td>
              ))}
              <Td>
                <Button size="sm" variant="secondary" onClick={() => setEdit(p)}>
                  Editar
                </Button>
              </Td>
            </tr>
          ))}
        </Table>
      )}
      {edit && (
        <Modal title={edit.id ? `Plano ${edit.nome}` : "Novo plano"} onClose={() => setEdit(null)}>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              salvar.mutate(edit);
            }}
          >
            {!planos.data?.some((p) => p.id === edit.id) && (
              <Field label="Identificador">
                <Input required pattern="[a-z0-9_-]+" value={edit.id} onChange={(e) => setEdit({ ...edit, id: e.target.value })} />
              </Field>
            )}
            <Field label="Nome">
              <Input required value={edit.nome} onChange={(e) => setEdit({ ...edit, nome: e.target.value })} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              {campos.map(([k, label]) => (
                <Field key={k} label={label}>
                  <Input type="number" min={k === "monitor_max" ? 0 : 1} required value={edit[k] as number} onChange={(e) => setEdit({ ...edit, [k]: Number(e.target.value) })} />
                </Field>
              ))}
            </div>
            <ErrorBox error={salvar.error} />
            <div className="text-right">
              <Button type="submit">Salvar</Button>
            </div>
          </form>
        </Modal>
      )}
    </Card>
  );
}

function Etl() {
  const etl = useQuery({
    queryKey: ["admin", "etl"],
    queryFn: () =>
      api<{
        base_servida: string | null;
        execucoes: { id: number; referencia: string; status: string; iniciado_em: string; duracao_s: number; erro: string | null; etapas: { etapa: string; arquivo: string | null; linhas: number | null; linhas_rejeitadas: number | null; duracao_ms: number | null; status: string; erro: string | null }[] }[];
      }>("/v1/admin/etl"),
    refetchInterval: 30_000,
  });
  const [aberta, setAberta] = useState<number | null>(null);
  if (etl.isLoading) return <Spinner />;
  return (
    <Card title={`Cargas da base da Receita — servindo ${etl.data?.base_servida ?? "nenhuma"}`}>
      <ErrorBox error={etl.error} />
      {etl.data?.execucoes.length === 0 && <Empty>Nenhuma carga executada ainda.</Empty>}
      <ul className="divide-y divide-slate-100">
        {etl.data?.execucoes.map((r) => (
          <li key={r.id} className="py-2">
            <button className="flex w-full items-center gap-3 text-left text-sm" onClick={() => setAberta(aberta === r.id ? null : r.id)}>
              <Badge tone={r.status === "success" ? "green" : r.status === "failed" ? "red" : "amber"}>{r.status}</Badge>
              <span className="font-medium">{r.referencia}</span>
              <span className="text-slate-500">{fmt.dateTime(r.iniciado_em)}</span>
              <span className="text-slate-500">{Math.round(r.duracao_s / 60)} min</span>
              {r.erro && <span className="truncate text-red-700">{r.erro}</span>}
            </button>
            {aberta === r.id && (
              <div className="mt-2">
                <Table head={["Etapa", "Arquivo", "Linhas", "Rejeitadas", "Duração", "Status"]}>
                  {r.etapas.map((s, i) => (
                    <tr key={i}>
                      <Td>{s.etapa}</Td>
                      <Td className="font-mono text-xs">{s.arquivo ?? ""}</Td>
                      <Td>{fmt.integer(s.linhas)}</Td>
                      <Td>{fmt.integer(s.linhas_rejeitadas)}</Td>
                      <Td>{((s.duracao_ms ?? 0) / 1000).toFixed(1)} s</Td>
                      <Td>{s.erro ? <span className="text-red-700">{s.erro}</span> : s.status}</Td>
                    </tr>
                  ))}
                </Table>
              </div>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function WebhooksFalhos() {
  const q = useQuery({
    queryKey: ["admin", "webhooks"],
    queryFn: () => api<{ id: number; status: string; tentativas: number; ultimo_erro: string | null; proxima_tentativa_em: string; url: string; chave: string; cnpj: string; tipo: string }[]>("/v1/admin/webhooks"),
  });
  return (
    <Card title="Entregas de webhook com problema">
      {q.data?.length === 0 && <Empty>Nenhuma falha de entrega.</Empty>}
      {q.data && q.data.length > 0 && (
        <Table head={["Destino", "Evento", "Status", "Tentativas", "Último erro"]}>
          {q.data.map((w) => (
            <tr key={w.id}>
              <Td>
                <div className="font-mono text-xs">{w.url}</div>
                <div className="text-xs text-slate-500">{w.chave}</div>
              </Td>
              <Td className="text-xs">
                {w.cnpj} · {w.tipo}
              </Td>
              <Td>
                <Badge tone={w.status === "falhou" ? "red" : "amber"}>{w.status}</Badge>
              </Td>
              <Td>{w.tentativas}</Td>
              <Td className="text-xs text-red-700">{w.ultimo_erro}</Td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

function UsoGeral() {
  const q = useQuery({
    queryKey: ["admin", "uso"],
    queryFn: () => api<{ api_key_id: number; nome: string; pessoal: boolean; plano: string; usuario_email: string | null; requisicoes: number; erros: number; ultimo_acesso: string | null }[]>("/v1/admin/uso"),
  });
  return (
    <Card title="Consumo nos últimos 30 dias">
      {q.data && (
        <Table head={["Conta / chave", "Plano", "Requisições", "Erros", "Último acesso"]}>
          {q.data.map((u) => (
            <tr key={u.api_key_id}>
              <Td>
                {u.pessoal ? u.usuario_email : u.nome} <Badge>{u.pessoal ? "painel" : "integração"}</Badge>
              </Td>
              <Td>{u.plano}</Td>
              <Td>{fmt.integer(u.requisicoes)}</Td>
              <Td>{fmt.integer(u.erros)}</Td>
              <Td className="text-xs">{fmt.dateTime(u.ultimo_acesso)}</Td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

function Auditoria() {
  const [filtro, setFiltro] = useState({ caminho: "", de: "", ate: "" });
  const [aplicado, setAplicado] = useState(filtro);
  const q = useQuery({
    queryKey: ["admin", "acessos", aplicado],
    queryFn: () =>
      api<{ criado_em: string; metodo: string; caminho: string; consulta: string | null; status: number; ip: string | null; usuario_email: string | null; chave: string | null }[]>(
        "/v1/admin/acessos",
        { query: { ...aplicado, limite: 500 } },
      ),
  });
  return (
    <Card title="Log de acesso (LGPD)">
      <form
        className="mb-4 grid gap-2 sm:grid-cols-[1fr_10rem_10rem_auto]"
        onSubmit={(e) => {
          e.preventDefault();
          setAplicado(filtro);
        }}
      >
        <Input placeholder="Trecho do caminho, ex.: um CNPJ" value={filtro.caminho} onChange={(e) => setFiltro({ ...filtro, caminho: e.target.value })} aria-label="Caminho" />
        <Input type="date" value={filtro.de} onChange={(e) => setFiltro({ ...filtro, de: e.target.value })} aria-label="De" />
        <Input type="date" value={filtro.ate} onChange={(e) => setFiltro({ ...filtro, ate: e.target.value })} aria-label="Até" />
        <Button type="submit" variant="secondary">
          Filtrar
        </Button>
      </form>
      {q.data && (
        <Table head={["Quando", "Quem", "Requisição", "Status", "IP"]}>
          {q.data.map((a, i) => (
            <tr key={i}>
              <Td className="whitespace-nowrap text-xs">{fmt.dateTime(a.criado_em)}</Td>
              <Td className="text-xs">{a.usuario_email ?? a.chave ?? "—"}</Td>
              <Td className="font-mono text-xs">
                {a.metodo} {a.caminho}
                {a.consulta ? `?${a.consulta}` : ""}
              </Td>
              <Td>{a.status}</Td>
              <Td className="text-xs">{a.ip ?? "—"}</Td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

export function Admin() {
  const [aba, setAba] = useState<Aba>("usuarios");
  return (
    <div>
      <PageTitle title="Administração" />
      <Tabs
        value={aba}
        onChange={setAba}
        tabs={[
          { id: "usuarios", label: "Usuários" },
          { id: "chaves", label: "Chaves de API" },
          { id: "planos", label: "Planos" },
          { id: "etl", label: "Cargas da Receita" },
          { id: "webhooks", label: "Webhooks" },
          { id: "uso", label: "Consumo" },
          { id: "auditoria", label: "Auditoria" },
        ]}
      />
      {aba === "usuarios" && <Usuarios />}
      {aba === "chaves" && <Chaves />}
      {aba === "planos" && <Planos />}
      {aba === "etl" && <Etl />}
      {aba === "webhooks" && <WebhooksFalhos />}
      {aba === "uso" && <UsoGeral />}
      {aba === "auditoria" && <Auditoria />}
    </div>
  );
}
