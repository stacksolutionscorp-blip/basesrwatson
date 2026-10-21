import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import { AuthProvider, useAuth } from "./hooks/auth";
import "./index.css";
import { ApiError } from "./lib/api";
import { Home } from "./pages/Home";
import { Login } from "./pages/Login";
import { Termos } from "./pages/Termos";

// Páginas com mapa, grafo e gráficos são carregadas sob demanda.
const Leads = lazy(() => import("./pages/Leads").then((m) => ({ default: m.Leads })));
const Empresa = lazy(() => import("./pages/Empresa").then((m) => ({ default: m.Empresa })));
const Busca = lazy(() => import("./pages/Busca").then((m) => ({ default: m.Busca })));
const Grafo = lazy(() => import("./pages/Grafo").then((m) => ({ default: m.Grafo })));
const Socios = lazy(() => import("./pages/Socios").then((m) => ({ default: m.Socios })));
const Lote = lazy(() => import("./pages/Lote").then((m) => ({ default: m.Lote })));
const Monitoramento = lazy(() => import("./pages/Monitoramento").then((m) => ({ default: m.Monitoramento })));
const Uso = lazy(() => import("./pages/Uso").then((m) => ({ default: m.Uso })));
const Admin = lazy(() => import("./pages/Admin").then((m) => ({ default: m.Admin })));
const Conta = lazy(() => import("./pages/Conta").then((m) => ({ default: m.Conta })));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (n, err) => !(err instanceof ApiError && err.status < 500) && n < 2,
    },
  },
});

function Gate() {
  const { usuario, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!usuario) return <Login />;
  if (usuario.termos_pendentes) return <Termos />;
  return (
    <Suspense fallback={<Spinner />}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="leads" element={<Leads />} />
          <Route path="empresa/:cnpj" element={<Empresa />} />
          <Route path="grafo/:cnpj" element={<Grafo />} />
          <Route path="busca" element={<Busca />} />
          <Route path="socios" element={<Socios />} />
          <Route path="lote" element={<Lote />} />
          <Route path="monitoramento" element={<Monitoramento />} />
          <Route path="uso" element={<Uso />} />
          <Route path="conta" element={<Conta />} />
          {usuario.papel === "admin" && <Route path="admin" element={<Admin />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Gate />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
