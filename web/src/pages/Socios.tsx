import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Badge, Button, Card, Empty, ErrorBox, Field, Input, PageTitle, Spinner, Table, Td } from "../components/ui";
import { api } from "../lib/api";
import * as fmt from "../lib/format";
import type { PessoaSocia } from "../lib/types";

export function Socios() {
  const [sp, setSp] = useSearchParams();
  const [nome, setNome] = useState(sp.get("nome") ?? "");
  const [cpf, setCpf] = useState(sp.get("cpf") ?? "");
  const busca = { nome: sp.get("nome") ?? "", cpf: sp.get("cpf") ?? "" };
  const res = useQuery({
    queryKey: ["socios", busca],
    queryFn: () => api<{ resultados: PessoaSocia[] }>("/v1/socios", { query: { ...busca, limite: 50 } }),
    enabled: busca.nome.length >= 3,
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSp(cpf ? { nome, cpf } : { nome });
  };

  return (
    <div className="space-y-5">
      <PageTitle title="Sócios" subtitle="Encontre uma pessoa (ou empresa) e todas as empresas em que ela aparece no quadro societário." />
      <Card>
        <form onSubmit={submit} className="grid gap-3 sm:grid-cols-[1fr_12rem_auto] sm:items-end">
          <Field label="Nome do sócio">
            <Input value={nome} onChange={(e) => setNome(e.target.value)} minLength={3} required placeholder="ex.: Maria da Silva" />
          </Field>
          <Field label="Dígitos do CPF (opcional)" hint="Os 6 visíveis na máscara">
            <Input value={cpf} onChange={(e) => setCpf(e.target.value)} inputMode="numeric" placeholder="123456" />
          </Field>
          <Button type="submit">Buscar</Button>
        </form>
      </Card>
      {res.isLoading && <Spinner />}
      <ErrorBox error={res.error} />
      {res.data && res.data.resultados.length === 0 && <Empty>Nenhum sócio encontrado.</Empty>}
      {res.data?.resultados.map((p, i) => (
        <Card
          key={i}
          title={
            <span className="flex items-center gap-2">
              {p.nome} <Badge>{p.tipo ?? "—"}</Badge>
              <span className="font-mono text-xs font-normal text-slate-500">{p.cpf_cnpj}</span>
            </span>
          }
        >
          <Table head={["Empresa", "Qualificação", "Entrada"]}>
            {p.empresas.map((e) => (
              <tr key={e.cnpj_basico}>
                <Td>
                  <Link className="font-medium text-brand-700 hover:underline" to={`/busca?q=${e.cnpj_basico}&matriz=true`}>
                    {e.razao_social ?? e.cnpj_basico}
                  </Link>
                  <div className="font-mono text-xs text-slate-500">raiz {e.cnpj_basico}</div>
                </Td>
                <Td>{e.qualificacao?.descricao ?? "—"}</Td>
                <Td>{fmt.date(e.data_entrada)}</Td>
              </tr>
            ))}
          </Table>
        </Card>
      ))}
    </div>
  );
}
