import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, type ReactNode } from "react";
import { ApiError, api, post, setAuthHandlers } from "../lib/api";
import type { Usuario } from "../lib/types";

interface AuthState {
  usuario: Usuario | null;
  loading: boolean;
  login: (email: string, senha: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<unknown>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const me = useQuery({
    queryKey: ["eu"],
    queryFn: async () => {
      try {
        return await api<Usuario>("/v1/auth/eu");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
    retry: false,
  });

  useEffect(() => {
    setAuthHandlers({
      unauthorized: () => qc.setQueryData(["eu"], null),
      termsPending: () => qc.invalidateQueries({ queryKey: ["eu"] }),
    });
  }, [qc]);

  const value: AuthState = {
    usuario: me.data ?? null,
    loading: me.isLoading,
    login: async (email, senha) => {
      await post("/v1/auth/login", { email, senha });
      await me.refetch();
    },
    logout: async () => {
      await post("/v1/auth/logout");
      // marca "sem usuário" (a tela de login aparece) e descarta os dados da sessão anterior
      qc.setQueryData(["eu"], null);
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "eu" });
    },
    refresh: () => me.refetch(),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth fora do AuthProvider");
  return v;
}
