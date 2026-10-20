import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useState } from "react";
import { useAuth } from "../hooks/auth";
import { SearchBox } from "./SearchBox";
import { cx } from "./ui";

const NAV = [
  { to: "/", label: "Início", end: true },
  { to: "/busca", label: "Busca avançada" },
  { to: "/socios", label: "Sócios" },
  { to: "/lote", label: "Consulta em lote" },
  { to: "/monitoramento", label: "Monitoramento" },
  { to: "/uso", label: "Uso da API" },
];

export function Layout() {
  const { usuario, logout } = useAuth();
  const [menu, setMenu] = useState(false);
  const { pathname } = useLocation();
  const nav = usuario?.papel === "admin" ? [...NAV, { to: "/admin", label: "Administração" }] : NAV;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-[1050] border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-2.5">
          <NavLink to="/" className="flex shrink-0 items-center gap-2 font-semibold text-slate-900">
            <img src="/favicon.svg" alt="" className="size-7" />
            <span className="hidden sm:inline">CNPJ Intel</span>
          </NavLink>
          {pathname !== "/" && (
            <div className="max-w-xl flex-1">
              <SearchBox />
            </div>
          )}
          <div className="ml-auto flex items-center gap-3 text-sm">
            <NavLink to="/conta" className="hidden text-slate-600 hover:text-slate-900 md:inline">
              {usuario?.nome}
            </NavLink>
            <button onClick={logout} className="text-slate-500 hover:text-slate-900">
              Sair
            </button>
            <button className="rounded p-1.5 text-slate-600 hover:bg-slate-100 lg:hidden" onClick={() => setMenu(!menu)} aria-label="Menu">
              ☰
            </button>
          </div>
        </div>
      </header>
      <div className="mx-auto flex max-w-7xl gap-8 px-4 py-6">
        <nav className={cx("w-52 shrink-0 lg:block", menu ? "fixed inset-0 top-12 z-[1040] block bg-white p-4" : "hidden")} onClick={() => setMenu(false)}>
          <ul className="space-y-0.5">
            {nav.map((n) => (
              <li key={n.to}>
                <NavLink
                  to={n.to}
                  end={n.end}
                  className={({ isActive }) =>
                    cx("block rounded-md px-3 py-2 text-sm font-medium", isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900")
                  }
                >
                  {n.label}
                </NavLink>
              </li>
            ))}
          </ul>
          <p className="mt-6 px-3 text-xs leading-relaxed text-slate-400">
            Fonte: Dados Abertos CNPJ — Receita Federal. CPFs exibidos apenas mascarados.
          </p>
        </nav>
        <main className="min-w-0 flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
