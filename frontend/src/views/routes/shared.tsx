"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ExternalLink, MapPin } from "lucide-react";
import type { Place } from "@/entities/place";
import { api } from "@/shared/api";

type SharedStop = {
  place_id: number;
  status: "planned" | "visited" | "skipped";
  place: Pick<Place, "id" | "name" | "region" | "latitude" | "longitude"> | null;
};

type SharedRoute = {
  name: string;
  trip_date: string | null;
  items: SharedStop[];
};

const stopStatuses: Record<SharedStop["status"], string> = {
  planned: "Запланировано",
  visited: "Посещено",
  skipped: "Пропущено",
};

export function SharedRouteView({ token }: { token: string }) {
  const [route, setRoute] = useState<SharedRoute | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) return;

    const abort = new AbortController();
    api<SharedRoute>(`/itineraries/shared/${encodeURIComponent(token)}`, {
      signal: abort.signal,
    })
      .then(setRoute)
      .catch((cause) => {
        if (cause.name !== "AbortError") setError(cause.message);
      });
    return () => abort.abort();
  }, [token]);

  return (
    <main className="page routes-page shared-route-page">
      <div className="routes-page-heading">
        <Link
          href="/"
          className="routes-back-map"
          aria-label="Вернуться к карте"
          title="Вернуться к карте"
        >
          <ArrowLeft size={24} aria-hidden="true" />
        </Link>
        <h1>{route?.name || "Общий маршрут"}</h1>
      </div>
      {!token && (
        <p role="alert" className="notice">
          В ссылке отсутствует идентификатор маршрута.
        </p>
      )}
      {token && !route && !error && <p role="status">Загрузка маршрута…</p>}
      {error && (
        <p role="alert" className="notice">
          {error}
        </p>
      )}
      {route && (
        <>
          <p className="shared-route-caption">
            Маршрут для просмотра
            {route.trip_date &&
              ` · ${new Date(`${route.trip_date}T00:00:00`).toLocaleDateString("ru-RU")}`}
          </p>
          {route.items.length ? (
            <ol className="shared-route-stops">
              {route.items.map((stop, index) => (
                <li className="shared-route-stop" key={stop.place_id}>
                  <span className="shared-route-number">{index + 1}</span>
                  <div className="shared-route-stop-content">
                    <h2>{stop.place?.name || "Место недоступно"}</h2>
                    {stop.place?.region && (
                      <p className="muted">
                        <MapPin size={14} aria-hidden="true" />
                        {stop.place.region}
                      </p>
                    )}
                    <span className="shared-route-status">
                      {stopStatuses[stop.status]}
                    </span>
                    {stop.place &&
                      Number.isFinite(stop.place.latitude) &&
                      Number.isFinite(stop.place.longitude) && (
                        <a
                          className="button button-outline"
                          href={`https://yandex.ru/maps/?pt=${stop.place.longitude},${stop.place.latitude}&z=16&l=map`}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          <ExternalLink size={14} aria-hidden="true" />
                          На карту
                        </a>
                      )}
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <p className="muted">В маршруте пока нет мест.</p>
          )}
        </>
      )}
    </main>
  );
}
