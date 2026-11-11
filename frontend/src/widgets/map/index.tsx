"use client";
import { useEffect, useRef, useState } from "react";
import type * as maplibregl from "maplibre-gl";
import type { GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FeatureCollection, Point } from "geojson";
import {
  Place,
  categoryVisual,
  categoryVisuals,
  categoryMarkerSvg,
} from "@/entities/place";
import { Crosshair, Layers, CircleDashed } from "lucide-react";
import { locationControl } from "./location-control";
const style = process.env.NEXT_PUBLIC_MAP_STYLE_URL;
type Props = {
  data?: FeatureCollection<Point> & { total: number };
  clustered?: boolean;
  onClusterChange?: (enabled: boolean) => void;
  places: Place[];
  selected: number | null;
  onSelect: (id: number) => void;
  onBounds?: (bbox: string, zoom: number) => void;
  onPoint?: (lon: number, lat: number) => void;
  pointHint?: string;
  showLabel?: boolean;
  editable?: boolean;
  markerDisabled?: boolean;
  center?: [number, number];
  focusBounds?: [number, number, number, number];
};
export function MapPanel({
  data,
  clustered = true,
  onClusterChange,
  places,
  selected,
  onSelect,
  onBounds,
  onPoint,
  pointHint,
  showLabel = true,
  editable = false,
  markerDisabled = false,
  center,
  focusBounds,
}: Props) {
  const [initial] = useState(() => ({ center, serverClusters: !!data }));
  const [accuracyVisible, setAccuracyVisible] = useState(false);
  const geolocation = useRef<ReturnType<typeof locationControl> | null>(null);
  const [locationError, setLocationError] = useState("");
  const root = useRef<HTMLDivElement>(null),
    map = useRef<maplibregl.Map | null>(null),
    [error, setError] = useState(
      style
        ? ""
        : "Картографическая подложка не настроена. Список и поиск доступны.",
    ),
    [ready, setReady] = useState(false);
  const editMarker = useRef<maplibregl.Marker | null>(null);
  const dragging = useRef(false);
  const currentPlaces = useRef(places);
  useEffect(() => {
    currentPlaces.current = places;
  }, [places]);
  const callbacks = useRef({ onSelect, onBounds, onPoint });
  useEffect(() => {
    callbacks.current = { onSelect, onBounds, onPoint };
  }, [onSelect, onBounds, onPoint]);
  useEffect(() => {
    if (!root.current) return;
    if (!style) return;
    let m: maplibregl.Map;
    let disposed = false;
    async function initialize() {
      try {
        const maplibregl = await import("maplibre-gl");
        if (disposed || !root.current || !style) return;
        const markers = await Promise.all(
          (
            Object.keys(categoryVisuals) as Array<keyof typeof categoryVisuals>
          ).map(async (key) => {
            const image = new Image();
            image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(categoryMarkerSvg(key))}`;
            await image.decode();
            const canvas = document.createElement("canvas");
            canvas.width = canvas.height = 72;
            const context = canvas.getContext("2d");
            if (!context) throw new Error("Marker rendering unavailable");
            context.drawImage(image, 0, 0);
            return { key, pixels: context.getImageData(0, 0, 72, 72) };
          }),
        );
        if (disposed) return;
        maplibregl.setWorkerUrl("/vendor/maplibre/maplibre-gl-worker.mjs");
        m = new maplibregl.Map({
          container: root.current,
          style,
          center: initial.center || [37.62, 55.75],
          zoom: initial.center ? 12 : 9,
          attributionControl: { compact: false },
          locale: {
            "GeolocateControl.FindMyLocation": "Моё местоположение",
            "GeolocateControl.LocationNotAvailable": "Местоположение недоступно",
          },
        });
        map.current = m;
        const observer = new ResizeObserver(() => m.resize());
        observer.observe(root.current);
        m.on("remove", () => observer.disconnect());
        m.addControl(new maplibregl.NavigationControl(), "bottom-right");
        geolocation.current = locationControl(maplibregl, setLocationError);
        m.addControl(geolocation.current, "bottom-right");
        m.on("error", () =>
          setError(
            "Не удалось загрузить карту. Проверьте соединение или повторите позже.",
          ),
        );
        m.on("load", () => {
          // Prefer Russian names, then the local spelling supplied by the tiles.
          for (const layer of m.getStyle().layers) {
            if (layer.type !== "symbol" || !layer.layout?.["text-field"])
              continue;
            const field = layer.layout["text-field"];
            if (!/name/.test(JSON.stringify(field))) continue;
            m.setLayoutProperty(layer.id, "text-field", [
              "coalesce",
              ["get", "name:ru"],
              ["get", "name_ru"],
              ["get", "name"],
              "",
            ]);
          }
          setReady(true);
          setError("");
          for (const marker of markers) {
            m.addImage(`category-${marker.key}`, marker.pixels, {
              pixelRatio: 2,
            });
          }
          m.addSource("places", {
            type: "geojson",
            data: { type: "FeatureCollection", features: [] },
            cluster: !initial.serverClusters,
            clusterRadius: 45,
            clusterMaxZoom: 14,
          });
          m.addLayer({
            id: "clusters",
            type: "circle",
            source: "places",
            filter: ["has", "point_count"],
            paint: {
              "circle-color": "#87bfe0",
              "circle-radius": [
                "step",
                ["get", "point_count"],
                18,
                20,
                24,
                80,
                30,
              ],
              "circle-stroke-width": 5,
              "circle-stroke-color": "#274052",
            },
          });
          m.addLayer({
            id: "cluster-count",
            type: "symbol",
            source: "places",
            filter: ["has", "point_count"],
            layout: {
              "text-field": ["get", "point_count_abbreviated"],
              "text-size": 12,
            },
            paint: { "text-color": "#101820" },
          });
          m.addLayer({
            id: "point-selection",
            type: "circle",
            source: "places",
            filter: ["!", ["has", "point_count"]],
            paint: {
              "circle-radius": 0,
              "circle-opacity": 0,
              "circle-stroke-width": 0,
              "circle-stroke-color": "#ffffff",
            },
          });
          m.addLayer({
            id: "points",
            type: "symbol",
            source: "places",
            filter: ["!", ["has", "point_count"]],
            layout: {
              "icon-image": [
                "coalesce",
                ["get", "category_icon"],
                "category-other",
              ],
              "icon-size": 1,
              "icon-allow-overlap": true,
              "icon-ignore-placement": true,
            },
          });
          for (const layer of ["points", "clusters"]) {
            m.on("mouseenter", layer, () => {
              m.getCanvas().style.cursor = "pointer";
            });
            m.on("mouseleave", layer, () => {
              m.getCanvas().style.cursor = "";
            });
          }
          m.on("click", "points", (e) => {
            const id = e.features?.[0]?.properties?.id;
            if (id) callbacks.current.onSelect(Number(id));
          });
          m.on("click", "clusters", async (e) => {
            const f = e.features?.[0];
            if (!f || f.geometry.type !== "Point") return;
            if (initial.serverClusters) {
              m.fitBounds(
                [
                  [f.properties.west, f.properties.south],
                  [f.properties.east, f.properties.north],
                ],
                { padding: 70, maxZoom: 22 },
              );
              return;
            }
            const zoom = await (
              m.getSource("places") as GeoJSONSource
            ).getClusterExpansionZoom(f.properties.cluster_id);
            m.easeTo({
              center: f.geometry.coordinates as [number, number],
              zoom,
            });
          });
          const publish = () => {
            const b = m.getBounds();
            const wrap = (lon: number) =>
              ((((lon + 180) % 360) + 360) % 360) - 180;
            const world = b.getEast() - b.getWest() >= 360;
            callbacks.current.onBounds?.(
              [
                world ? -180 : wrap(b.getWest()),
                Math.max(-90, b.getSouth()),
                world ? 180 : wrap(b.getEast()),
                Math.min(90, b.getNorth()),
              ].join(","),
              Math.floor(m.getZoom()),
            );
          };
          publish();
          m.on("moveend", publish);
        });
      } catch (cause) {
        console.error("Map initialization failed", cause);
        setError(
          "Не удалось запустить карту. Попробуйте обновить страницу или используйте список.",
        );
      }
    }
    void initialize();
    return () => {
      disposed = true;
      m?.remove();
      map.current = null;
      geolocation.current = null;
    };
  }, [initial]);
  useEffect(() => {
    geolocation.current?.setAccuracyVisible(accuracyVisible);
  }, [accuracyVisible, ready]);
  useEffect(() => {
    if (!ready || !map.current || !editable) return;
    const m = map.current;
    let cancelled = false;
    let marker: maplibregl.Marker | undefined;
    for (const layer of ["points", "point-selection"])
      m.setLayoutProperty(layer, "visibility", "none");
    void import("maplibre-gl").then((lib) => {
      if (cancelled || !currentPlaces.current[0]) return;
      const p = currentPlaces.current[0];
      marker = new lib.Marker({ draggable: true, color: "#8ac4e4" })
        .setLngLat([p.longitude, p.latitude])
        .addTo(m);
      editMarker.current = marker;
      marker.getElement().setAttribute("aria-label", "Переместить точку места");
      marker.getElement().style.cursor = "grab";
      const publish = () => {
        const point = marker!.getLngLat().wrap();
        callbacks.current.onPoint?.(
          point.lng,
          Math.max(-85, Math.min(85, point.lat)),
        );
      };
      marker.on("dragstart", () => {
        dragging.current = true;
      });
      marker.on("drag", publish);
      marker.on("dragend", () => {
        dragging.current = false;
        publish();
      });
    });
    return () => {
      cancelled = true;
      marker?.remove();
      editMarker.current = null;
      dragging.current = false;
      if (map.current === m)
        for (const layer of ["points", "point-selection"])
          if (m.getLayer(layer))
            m.setLayoutProperty(layer, "visibility", "visible");
    };
  }, [ready, editable]);
  useEffect(() => {
    if (!dragging.current && places[0])
      editMarker.current?.setLngLat([places[0].longitude, places[0].latitude]);
    editMarker.current?.setDraggable(!markerDisabled);
  }, [places, markerDisabled]);
  useEffect(() => {
    if (!ready || !map.current?.getSource("places")) return;
    (map.current.getSource("places") as GeoJSONSource).setData(
      data
        ? {
            ...data,
            features: data.features.map((feature) => ({
              ...feature,
              properties: {
                ...feature.properties,
                category_icon: `category-${categoryVisual(feature.properties?.category_icon).key}`,
              },
            })),
          }
        : {
            type: "FeatureCollection",
            features: places.map((p) => ({
              type: "Feature",
              geometry: {
                type: "Point",
                coordinates: [p.longitude, p.latitude],
              },
              properties: {
                id: p.id,
                category_icon: `category-${categoryVisual(p.category_icon).key}`,
              },
            })),
          },
    );
  }, [data, places, ready]);
  useEffect(() => {
    const m = map.current;
    if (ready && m?.getLayer("points")) {
      const selectedSize = (size: number): maplibregl.ExpressionSpecification => [
        "case", ["==", ["get", "id"], selected ?? -1], size * 1.2, size,
      ];
      m.setLayoutProperty("points", "icon-size", clustered ? selectedSize(1) : [
        "interpolate", ["linear"], ["zoom"],
        3, selectedSize(0.3),
        8, selectedSize(0.5),
        12, selectedSize(0.8),
        15, selectedSize(1),
      ]);
      const selectedRadius = (radius: number): maplibregl.ExpressionSpecification => [
        "case", ["==", ["get", "id"], selected ?? -1], radius, 0,
      ];
      m.setPaintProperty("point-selection", "circle-radius", clustered ? selectedRadius(23) : [
        "interpolate", ["linear"], ["zoom"],
        3, selectedRadius(7),
        8, selectedRadius(11.5),
        12, selectedRadius(18.4),
        15, selectedRadius(23),
      ]);
      m.setPaintProperty("point-selection", "circle-stroke-width", [
        "case",
        ["==", ["get", "id"], selected ?? -1],
        2,
        0,
      ]);
    }
  }, [selected, ready, clustered]);
  useEffect(() => {
    if (!ready || !map.current || !focusBounds || dragging.current) return;
    const [west, south, east, north] = focusBounds;
    map.current.fitBounds(
      [
        [west, south],
        [east, north],
      ],
      { padding: 48, maxZoom: 14, duration: 650 },
    );
  }, [focusBounds, ready]);
  return (
    <div className="map-wrap">
      <div ref={root} className="map-canvas" />
      {showLabel && <div className="map-label">
        {onClusterChange ? (
          <button type="button" className="map-cluster-toggle"
            aria-label="Группировка мест" aria-pressed={clustered}
            title={clustered ? "Отключить группировку" : "Включить группировку"}
            onClick={() => onClusterChange(!clustered)}>
            <Layers size={16} aria-hidden="true" />
          </button>
        ) : <Layers size={14} aria-hidden="true" />}
        <button type="button" className="map-cluster-toggle"
          aria-label="Погрешность геолокации" aria-pressed={accuracyVisible}
          title={accuracyVisible ? "Скрыть погрешность геолокации" : "Показать погрешность геолокации"}
          onClick={() => setAccuracyVisible((visible) => !visible)}>
          <CircleDashed size={16} aria-hidden="true" />
        </button>
        КАРТА ОБЪЕКТОВ <span>•</span> {data?.total ?? places.length} в области
      </div>}
      {error && (
        <div className="map-error" role="status">
          <Crosshair size={28} />
          <strong>Карта недоступна</strong>
          <p>{error}</p>
        </div>
      )}
      <div className="sr-only" role="status" data-testid="map-location-status">
        {locationError || pointHint || "Двойной щелчок — поиск рядом с точкой"}
      </div>
    </div>
  );
}
