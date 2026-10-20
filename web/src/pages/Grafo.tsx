import { useQuery } from "@tanstack/react-query";
import cytoscape from "cytoscape";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Badge, Button, Card, ErrorBox, PageTitle, Select, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { cleanCnpj, formatCnpj } from "../lib/cnpj";
import type { Grafo as GrafoT } from "../lib/types";

const SITUACAO_COR: Record<string, string> = { ATIVA: "#2557e6", BAIXADA: "#94a3b8", NULA: "#94a3b8" };

export function Grafo() {
  const { cnpj = "" } = useParams();
  const c = cleanCnpj(cnpj);
  const [niveis, setNiveis] = useState(2);
  const [selecionado, setSelecionado] = useState<GrafoT["nodes"][number] | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const cy = useRef<cytoscape.Core | null>(null);
  const navigate = useNavigate();
  const grafo = useQuery({ queryKey: ["grafo", c, niveis], queryFn: () => api<GrafoT>(`/v1/grafo/${c}`, { query: { niveis } }) });

  useEffect(() => {
    if (!ref.current || !grafo.data) return;
    const raiz = `empresa:${c.slice(0, 8)}`;
    cy.current = cytoscape({
      container: ref.current,
      elements: [
        ...grafo.data.nodes.map((n) => ({
          data: {
            id: n.id,
            label: n.label ?? n.id.split(":")[1],
            tipo: n.tipo,
            cor: n.tipo === "pessoa" ? "#f59e0b" : SITUACAO_COR[String(n.dados.situacao)] ?? "#d97706",
            raiz: n.id === raiz ? 1 : 0,
            nivel: n.nivel,
          },
        })),
        ...grafo.data.edges.map((e, i) => ({ data: { id: `e${i}`, source: e.source, target: e.target, label: e.qualificacao ?? "" } })),
      ],
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "background-color": "data(cor)",
            "font-size": 10,
            "text-wrap": "wrap",
            "text-max-width": "120px",
            "text-valign": "bottom",
            "text-margin-y": 4,
            color: "#334155",
            width: 26,
            height: 26,
          },
        },
        { selector: 'node[tipo = "empresa"]', style: { shape: "round-rectangle" } },
        { selector: "node[raiz = 1]", style: { width: 40, height: 40, "border-width": 4, "border-color": "#172f75" } },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#cbd5e1",
            "target-arrow-color": "#cbd5e1",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
          },
        },
        // a qualificação aparece só na ligação selecionada (com muitas ligações os rótulos poluem)
        {
          selector: "edge:selected",
          style: { label: "data(label)", "font-size": 9, color: "#475569", "text-rotation": "autorotate", "line-color": "#64748b", "target-arrow-color": "#64748b" },
        },
        { selector: "node:selected", style: { "border-width": 3, "border-color": "#0f172a" } },
      ],
      // layout de força: repulsão alta e arestas longas para os rótulos não se sobreporem
      layout: {
        name: "cose",
        animate: false,
        randomize: false,
        nodeRepulsion: () => 400_000,
        idealEdgeLength: () => 120,
        nodeOverlap: 40,
        gravity: 0.25,
        numIter: 1500,
        padding: 50,
      },
      wheelSensitivity: 0.2,
      minZoom: 0.2,
      maxZoom: 1.5, // com poucos nós o ajuste automático ampliaria demais
    });
    cy.current.on("tap", "node", (evt) => {
      const node = grafo.data!.nodes.find((n) => n.id === evt.target.id()) ?? null;
      setSelecionado(node);
    });
    return () => {
      cy.current?.destroy();
      cy.current = null;
    };
  }, [grafo.data, c]);

  const abrir = () => {
    if (!selecionado) return;
    if (selecionado.tipo === "empresa") {
      const matriz = selecionado.dados.cnpj_matriz as string | undefined;
      if (matriz) navigate(`/empresa/${matriz}`);
    } else {
      navigate(`/socios?nome=${encodeURIComponent(selecionado.label ?? "")}`);
    }
  };

  return (
    <div className="space-y-5">
      <PageTitle
        title="Rede societária"
        subtitle={
          <>
            A partir de <Link className="text-brand-700 hover:underline" to={`/empresa/${c}`}>{formatCnpj(c)}</Link>. Clique em um nó para ver detalhes.
          </>
        }
        actions={
          <Select value={niveis} onChange={(e) => setNiveis(Number(e.target.value))} aria-label="Níveis">
            <option value={1}>1 nível</option>
            <option value={2}>2 níveis</option>
            <option value={3}>3 níveis</option>
          </Select>
        }
      />
      <ErrorBox error={grafo.error} />
      {grafo.data?.truncado && <ErrorBox error="A rede é grande e foi cortada no limite de nós. Reduza os níveis para ver os detalhes." />}
      <div className="grid gap-5 lg:grid-cols-4">
        <Card className="lg:col-span-3">
          {grafo.isLoading && <Spinner />}
          <div ref={ref} className="h-[36rem] w-full" data-testid="grafo" />
          <div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-500">
            <span><span className="mr-1 inline-block size-2.5 rounded-sm bg-[#2557e6]" />Empresa ativa</span>
            <span><span className="mr-1 inline-block size-2.5 rounded-sm bg-slate-400" />Empresa baixada/nula</span>
            <span><span className="mr-1 inline-block size-2.5 rounded-full bg-amber-500" />Pessoa</span>
          </div>
        </Card>
        <Card title="Detalhes">
          {!selecionado ? (
            <p className="text-sm text-slate-500">
              {grafo.data ? `${grafo.data.nodes.length} nós e ${grafo.data.edges.length} ligações.` : ""} Selecione um nó.
            </p>
          ) : (
            <div className="space-y-2 text-sm">
              <Badge tone={selecionado.tipo === "empresa" ? "blue" : "amber"}>{selecionado.tipo}</Badge>
              <p className="font-medium text-slate-900">{selecionado.label}</p>
              {Object.entries(selecionado.dados)
                .filter(([, v]) => v)
                .map(([k, v]) => (
                  <p key={k} className="text-slate-600">
                    <span className="text-slate-400">{k.replace(/_/g, " ")}:</span> {String(v)}
                  </p>
                ))}
              <Button size="sm" onClick={abrir}>
                {selecionado.tipo === "empresa" ? "Abrir empresa" : "Ver empresas desta pessoa"}
              </Button>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
