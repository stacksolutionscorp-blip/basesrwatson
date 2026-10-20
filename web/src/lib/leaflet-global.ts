import L from "leaflet";

// leaflet.markercluster é um plugin UMD que usa o Leaflet do global `L` ao ser carregado.
// Este módulo é importado antes dele (a ordem dos imports define a ordem de execução).
(window as unknown as { L: typeof L }).L = L;

export default L;
