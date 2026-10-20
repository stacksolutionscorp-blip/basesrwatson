import { useState, type FormEvent } from "react";
import { Button, ErrorBox, Field, Input } from "../components/ui";
import { useAuth } from "../hooks/auth";

export function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState<unknown>(null);
  const [enviando, setEnviando] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setEnviando(true);
    setErro(null);
    try {
      await login(email, senha);
    } catch (err) {
      setErro(err);
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-b from-brand-50 to-slate-50 px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="mb-6 flex items-center gap-2">
          <img src="/favicon.svg" alt="" className="size-8" />
          <div>
            <h1 className="font-semibold text-slate-900">CNPJ Intel</h1>
            <p className="text-xs text-slate-500">Inteligência empresarial por CNPJ</p>
          </div>
        </div>
        <div className="space-y-4">
          <Field label="E-mail">
            <Input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
          </Field>
          <Field label="Senha">
            <Input type="password" autoComplete="current-password" required value={senha} onChange={(e) => setSenha(e.target.value)} />
          </Field>
          <ErrorBox error={erro} />
          <Button type="submit" className="w-full" disabled={enviando}>
            {enviando ? "Entrando…" : "Entrar"}
          </Button>
        </div>
        <p className="mt-6 text-xs text-slate-400">Acesso por convite. Peça uma conta ao administrador.</p>
      </form>
    </div>
  );
}
