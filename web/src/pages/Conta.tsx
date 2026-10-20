import { useState, type FormEvent } from "react";
import { Button, Card, ErrorBox, Field, Input, KV, PageTitle } from "../components/ui";
import { useAuth } from "../hooks/auth";
import { post } from "../lib/api";
import * as fmt from "../lib/format";

export function Conta() {
  const { usuario } = useAuth();
  const [atual, setAtual] = useState("");
  const [nova, setNova] = useState("");
  const [confirma, setConfirma] = useState("");
  const [erro, setErro] = useState<unknown>(null);
  const [ok, setOk] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setOk(false);
    setErro(null);
    if (nova !== confirma) return setErro("A confirmação não confere com a nova senha.");
    try {
      await post("/v1/auth/senha", { atual, nova });
      setOk(true);
      setAtual("");
      setNova("");
      setConfirma("");
    } catch (err) {
      setErro(err);
    }
  };

  if (!usuario) return null;
  return (
    <div className="space-y-5">
      <PageTitle title="Minha conta" />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Dados">
          <KV
            items={[
              ["Nome", usuario.nome],
              ["E-mail", usuario.email],
              ["Papel", usuario.papel === "admin" ? "Administrador" : "Usuário"],
              ["Plano", usuario.plano.id],
              ["Termos aceitos", usuario.termos_versao],
              ["Requisições por dia", fmt.integer(usuario.plano.req_por_dia)],
            ]}
          />
        </Card>
        <Card title="Trocar senha">
          <form onSubmit={submit} className="space-y-3">
            <Field label="Senha atual">
              <Input type="password" autoComplete="current-password" required value={atual} onChange={(e) => setAtual(e.target.value)} />
            </Field>
            <Field label="Nova senha" hint="Mínimo de 10 caracteres, misturando letras e números ou símbolos">
              <Input type="password" autoComplete="new-password" required minLength={10} value={nova} onChange={(e) => setNova(e.target.value)} />
            </Field>
            <Field label="Confirme a nova senha">
              <Input type="password" autoComplete="new-password" required value={confirma} onChange={(e) => setConfirma(e.target.value)} />
            </Field>
            <ErrorBox error={erro} />
            {ok && <p className="text-sm text-emerald-700">Senha alterada. As outras sessões foram encerradas.</p>}
            <Button type="submit">Salvar</Button>
          </form>
        </Card>
      </div>
    </div>
  );
}
