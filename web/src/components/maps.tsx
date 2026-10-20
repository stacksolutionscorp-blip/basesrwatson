import L from "../lib/leaflet-global";
import "leaflet.markercluster";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";
import { useEffect, useRef } from "react";

// Servidores públicos do OSM servem uso moderado; em produção com muito tráfego use outro provedor
// (ou um servidor de tiles próprio) via VITE_TILE_URL no build.
const TILES = import.meta.env.VITE_TILE_URL || "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';
const BRASIL: L.LatLngTuple = [-14.5, -52];

function baseMap(el: HTMLElement, center: L.LatLngTuple, zoom: number) {
  const map = L.map(el, { scrollWheelZoom: false }).setView(center, zoom);
  L.tileLayer(TILES, { attribution: ATTRIBUTION, maxZoom: 19 }).addTo(map);
  return map;
}

const dot = (color: string) => ({ radius: 8, color: "#fff", weight: 2, fillColor: color, fillOpacity: 0.95 });

/** Mapa de um ponto. Precisão "municipio" é desenhada como área aproximada. */
export function PointMap({ lat, lng, label, precisao }: { lat: number; lng: number; label: string; precisao: string | null }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const aproximado = precisao === "municipio" || precisao === "cep";
    const map = baseMap(ref.current, [lat, lng], aproximado ? 12 : 16);
    if (aproximado) {
      L.circle([lat, lng], { radius: precisao === "cep" ? 400 : 3000, color: "#2557e6", weight: 1, fillOpacity: 0.08 }).addTo(map);
    }
    L.circleMarker([lat, lng], dot("#2557e6")).addTo(map).bindPopup(label);
    return () => {
      map.remove();
    };
  }, [lat, lng, label, precisao]);
  return <div ref={ref} className="h-72 w-full" data-testid="mapa" />;
}

export interface MapPoint {
  id: string;
  lat: number;
  lng: number;
  title: string;
  subtitle?: string;
  href?: string;
  color?: string;
}

/**
 * Mapa com agrupamento (clusters) por região. ``onPick`` permite clicar para escolher um centro
 * (busca por raio); ``circle`` desenha o raio atual.
 */
export function ClusterMap({
  points,
  circle,
  onPick,
  onOpen,
  height = "h-[28rem]",
}: {
  points: MapPoint[];
  circle?: { lat: number; lng: number; km: number } | null;
  onPick?: (lat: number, lng: number) => void;
  onOpen?: (p: MapPoint) => void;
  height?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const circleLayer = useRef<L.Circle | null>(null);
  const pick = useRef(onPick);
  const open = useRef(onOpen);
  pick.current = onPick;
  open.current = onOpen;

  useEffect(() => {
    if (!ref.current) return;
    map.current = baseMap(ref.current, BRASIL, 4);
    map.current.on("click", (e: L.LeafletMouseEvent) => pick.current?.(e.latlng.lat, e.latlng.lng));
    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    layer.current?.remove();
    const group = L.markerClusterGroup({ showCoverageOnHover: false, maxClusterRadius: 50 });
    const bounds: L.LatLngTuple[] = [];
    for (const p of points) {
      const marker = L.circleMarker([p.lat, p.lng], dot(p.color ?? "#2557e6"));
      const popup = document.createElement("div");
      popup.innerHTML = `<strong></strong><br><span style="color:#64748b"></span>`;
      popup.querySelector("strong")!.textContent = p.title;
      popup.querySelector("span")!.textContent = p.subtitle ?? "";
      if (onOpen) {
        const a = document.createElement("button");
        a.textContent = "Abrir empresa →";
        a.style.cssText = "display:block;margin-top:6px;color:#1d45c4;font-weight:600";
        a.onclick = () => open.current?.(p);
        popup.appendChild(a);
      }
      marker.bindPopup(popup);
      group.addLayer(marker as unknown as L.Marker);
      bounds.push([p.lat, p.lng]);
    }
    group.addTo(m);
    layer.current = group;
    if (circle) {
      m.fitBounds(L.latLng(circle.lat, circle.lng).toBounds(circle.km * 2000), { maxZoom: 15 });
    } else if (bounds.length) {
      m.fitBounds(L.latLngBounds(bounds), { padding: [30, 30], maxZoom: 14 });
    }
  }, [points, circle, onOpen]);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    circleLayer.current?.remove();
    circleLayer.current = circle
      ? L.circle([circle.lat, circle.lng], { radius: circle.km * 1000, color: "#2557e6", weight: 1.5, fillOpacity: 0.06 }).addTo(m)
      : null;
  }, [circle]);

  return <div ref={ref} className={`${height} w-full`} data-testid="mapa-clusters" />;
}
