import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Button, ErrorBox, Spinner } from "../components/ui";
import { useAuth } from "../hooks/auth";
import { api, post } from "../lib/api";
import { Markdown } from "../components/Markdown";

/** Tela de aceite obrigatório dos termos de uso (LGPD) antes de usar o painel. */
export function Termos() {
  const { refresh, logout, usuario } = useAuth();
  const termos = useQuery({ queryKey: ["termos"], queryFn: () => api<{ versao: string; texto: string }>("/v1/termos") });
  const [li, setLi] = useState(false);
  const [erro, setErro] = useState<unknown>(null);

  const aceitar = async () => {
    try {
      await post("/v1/auth/termos", { versao: termos.data!.versao });
      await refresh();
    } catch (e) {
      setErro(e);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10">
      <div className="w-full max-w-2xl rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <p className="mb-4 text-sm text-slate-500">
          {usuario?.termos_versao ? "Os termos de uso foram atualizados." : "Antes de continuar, leia e aceite os termos de uso."}
        </p>
        {termos.isLoading && <Spinner />}
        <ErrorBox error={termos.error} />
        {termos.data && (
          <>
            <div className="max-h-[55vh] overflow-auto rounded-lg border border-slate-100 bg-slate-50 p-5">
              <Markdown text={termos.data.texto} />
            </div>
            <p className="mt-2 text-xs text-slate-400">Versão {termos.data.versao}</p>
            <label className="mt-5 flex items-start gap-2 text-sm text-slate-700">
              <input type="checkbox" className="mt-0.5" checked={li} onChange={(e) => setLi(e.target.checked)} />
              Li e concordo com os termos de uso e com o registro das minhas consultas.
            </label>
            <ErrorBox error={erro} />
            <div className="mt-5 flex justify-between">
              <Button variant="ghost" onClick={logout}>
                Sair
              </Button>
              <Button disabled={!li} onClick={aceitar}>
                Aceitar e continuar
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
