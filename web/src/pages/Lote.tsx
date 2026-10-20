import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Button, Card, ErrorBox, PageTitle, SituacaoBadge, Table, Td } from "../components/ui";
import { useAuth } from "../hooks/auth";
import { post } from "../lib/api";
import { formatCnpj } from "../lib/cnpj";
import * as fmt from "../lib/format";
import type { Perfil } from "../lib/types";

type Item = { cnpj: string; ok: boolean; erro: string | null; dados: Perfil | null };

function extract(text: string): string[] {
  // aceita qualquer separação (linhas, vírgulas, ponto e vírgula, colunas coladas do Excel)
  return [...new Set(text.split(/[\s,;|]+/).map((t) => t.trim()).filter((t) => t.replace(/[^0-9A-Za-z]/g, "").length >= 14))];
}

function toCsv(items: Item[]): string {
  const head = ["cnpj", "status", "razao_social", "nome_fantasia", "situacao", "municipio", "uf", "cnae_principal", "capital_social", "abertura", "score_risco", "erro"];
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const rows = items.map((i) => {
    const d = i.dados;
    return [i.cnpj, i.ok ? "ok" : "erro", d?.razao_social, d?.nome_fantasia, d?.situacao.descricao, d?.endereco.municipio.nome, d?.endereco.uf,
      d?.cnae_principal?.codigo, d?.capital_social, d?.data_inicio, d?.score_risco.score, i.erro].map(esc).join(";"); // prettier-ignore
  });
  return "﻿" + [head.join(";"), ...rows].join("\n");
}

export function Lote() {
  const { usuario } = useAuth();
  const max = usuario?.plano.lote_max ?? 500;
  const [texto, setTexto] = useState("");
  const cnpjs = extract(texto);
  const lote = useMutation({
    mutationFn: async (lista: string[]) => {
      const out: Item[] = [];
      for (let i = 0; i < lista.length; i += max) {
        const r = await post<{ resultados: Item[] }>("/v1/lote", { cnpjs: lista.slice(i, i + max) });
        out.push(...r.resultados);
      }
      return out;
    },
  });

  const baixar = () => {
    const url = URL.createObjectURL(new Blob([toCsv(lote.data ?? [])], { type: "text/csv;charset=utf-8" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "consulta-lote.csv" });
    a.click();
    URL.revokeObjectURL(url);
  };

  const ok = lote.data?.filter((i) => i.ok).length ?? 0;
  return (
    <div className="space-y-5">
      <PageTitle title="Consulta em lote" subtitle={`Cole CNPJs separados por linha, vírgula ou ponto e vírgula. Enviados em blocos de ${max}.`} />
      <Card>
        <textarea
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          rows={8}
          aria-label="CNPJs"
          placeholder={"11.222.333/0001-81\n33.000.167/0001-01"}
          className="block w-full rounded-md border-0 p-3 font-mono text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-brand-500 focus:outline-none"
        />
        <div className="mt-3 flex items-center gap-3">
          <Button disabled={!cnpjs.length || lote.isPending} onClick={() => lote.mutate(cnpjs)}>
            {lote.isPending ? "Consultando…" : `Consultar ${cnpjs.length || ""} CNPJ${cnpjs.length === 1 ? "" : "s"}`}
          </Button>
          {lote.data && (
            <Button variant="secondary" onClick={baixar}>
              Baixar planilha (CSV)
            </Button>
          )}
          {lote.data && (
            <span className="text-sm text-slate-500">
              {ok} encontrados · {lote.data.length - ok} com erro
            </span>
          )}
        </div>
      </Card>
      <ErrorBox error={lote.error} />
      {lote.data && (
        <Card title="Resultado">
          <Table head={["CNPJ", "Empresa", "Situação", "Município", "Risco", ""]}>
            {lote.data.map((i) => (
              <tr key={i.cnpj}>
                <Td className="font-mono text-xs">{formatCnpj(i.cnpj)}</Td>
                <Td>
                  {i.dados ? (
                    <Link className="font-medium text-brand-700 hover:underline" to={`/empresa/${i.dados.cnpj}`}>
                      {i.dados.razao_social}
                    </Link>
                  ) : (
                    <span className="text-red-700">{i.erro}</span>
                  )}
                </Td>
                <Td>{i.dados && <SituacaoBadge situacao={i.dados.situacao.descricao} />}</Td>
                <Td>{i.dados ? `${i.dados.endereco.municipio.nome ?? ""}/${i.dados.endereco.uf ?? ""}` : ""}</Td>
                <Td>{i.dados ? `${i.dados.score_risco.score} (${i.dados.score_risco.nivel})` : ""}</Td>
                <Td className="text-xs text-slate-500">{i.dados && fmt.money(i.dados.capital_social)}</Td>
              </tr>
            ))}
          </Table>
        </Card>
      )}
    </div>
  );
}
