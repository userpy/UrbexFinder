"use client";
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowUpDown,
  Plus,
  Trash2,
  Pencil,
  Save,
  FileCheck,
  ChevronUp,
  ListRestart,
  Send,
} from "lucide-react";
import Link from "next/link";
import { useSession } from "@/entities/session";
import { Place } from "@/entities/place";
import { api, body, Page } from "@/shared/api";
import { PlaceDetail } from "@/widgets/place-detail";
import { Button } from "@/shared/ui/button";
type Stop = {
  place_id: number;
  note: string;
  status: "planned" | "visited" | "skipped";
};
type Route = {
  id: number;
  name: string;
  trip_date: string | null;
  created_at: string;
  active: boolean;
  notes: string;
  stops: Stop[];
  version: number;
  items?: (Stop & { place: Place | null })[];
};
export function RoutesView() {
  const { user, loading } = useSession();
  const [routes, setRoutes] = useState<Route[]>([]),
    [route, setRoute] = useState<Route | null>(null);
  const [error, setError] = useState(""),
    [message, setMessage] = useState("");
  const [pending, setPending] = useState<Place | null>(null),
    [selected, setSelected] = useState<Place | null>(null);
  const [sortDirection, setSortDirection] = useState<"asc" | "desc" | null>(null);
  const [choosing, setChoosing] = useState(false);
  const [routesLoading, setRoutesLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false),
    [page, setPage] = useState(1),
    [total, setTotal] = useState(0),
    [revision, setRevision] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState<Route | null>(null);
  const [deleteError, setDeleteError] = useState("");
  const deleteDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (message !== "Сохранено") return;
    const timer = setTimeout(() => setMessage(""), 3000);
    return () => clearTimeout(timer);
  }, [message]);
  useEffect(() => {
    if (deleteTarget) deleteDialog.current?.showModal();
  }, [deleteTarget]);
  const routeId = route?.id;
  useEffect(() => {
    if (!user) return;
    const abort = new AbortController();
    api<Page<Route>>(`/itineraries?page=${page}`, { signal: abort.signal })
      .then(async (d) => {
        setRoutes(d.items);
        setTotal(d.total);
        if (!choosing && !routeId && d.items.length) {
          const active = d.items.find((item) => item.active) || d.items[0];
          if (!active.active) {
            await api(`/itineraries/${active.id}/active?active=true`, {
              method: "PUT",
              signal: abort.signal,
            });
          }
          const detail = await api<Route>(`/itineraries/${active.id}`, {
            signal: abort.signal,
          });
          setRoute(detail);
        }
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setRoutesLoading(false);
      });
    return () => abort.abort();
  }, [user, page, revision, choosing, routeId]);
  useEffect(() => {
    const id = Number(new URLSearchParams(window.location.search).get("add"));
    if (id > 0)
      api<Place>(`/places/${id}`)
        .then(setPending)
        .catch((e) => setError(e.message));
  }, []);
  async function open(id: number) {
    setSortDirection(null);
    setEditing(false);
    setBusy(true);
    setError("");
    setMessage("");
    try {
      setRoute(await api<Route>(`/itineraries/${id}`));
      setChoosing(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    if (!route) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api(`/itineraries/${route.id}`, {
        method: "PUT",
        body: body({
          name: route.name,
          trip_date: route.trip_date,
          notes: route.notes,
          stops: route.stops,
          version: route.version,
        }),
      });
      setRoute(await api<Route>(`/itineraries/${route.id}`));
      setRevision((v) => v + 1);
      setMessage("Сохранено");
      setEditing(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function sortPlaces(direction: "asc" | "desc") {
    if (!route || busy) return;
    const names = new Map(
      route.items?.map((item) => [item.place_id, item.place?.name || "Место недоступно"]),
    );
    const stops = [...route.stops].sort((a, b) => {
      const comparison = (names.get(a.place_id) || "Место недоступно").localeCompare(
        names.get(b.place_id) || "Место недоступно",
        "ru",
        { numeric: true, sensitivity: "base" },
      );
      return direction === "asc" ? comparison : -comparison;
    });
    setRoute({ ...route, stops });
    setSortDirection(direction);
    setMessage("");
  }
  function updateStop(index: number, values: Partial<Stop>) {
    if (route)
      setRoute({
        ...route,
        stops: route.stops.map((s, i) =>
          i === index ? { ...s, ...values } : s,
        ),
      });
  }
  if (loading) return <main className="page routes-page">Загрузка…</main>;
  if (!user)
    return (
      <main className="page routes-page">
        <div className="routes-page-heading">
          <Link
            href="/"
            className="routes-back-map"
            aria-label="Вернуться к карте"
            title="Вернуться к карте"
          >
            <ArrowLeft size={24} aria-hidden="true" />
          </Link>
          <h1>Мои маршруты</h1>
        </div>
        <p>Войдите, чтобы составить личный маршрутный лист.</p>
        <Link
          href={`/login?next=${encodeURIComponent(`/routes${pending ? `?add=${pending.id}` : ""}`)}`}
        >
          Войти
        </Link>
      </main>
    );
  return (
    <main className="page routes-page">
      <div className="routes-page-heading">
        <Link
          href="/"
          className="routes-back-map"
          aria-label="Вернуться к карте"
          title="Вернуться к карте"
        >
          <ArrowLeft size={24} aria-hidden="true" />
        </Link>
        <h1>Мои маршруты</h1>
      </div>
      {!route && (
        <p className="muted">
          Личный план поездки. Карта места открывается кнопкой «На карту».
        </p>
      )}
      {error && (
        <p role="alert" className="notice">
          {error}
        </p>
      )}
      {message && (
        <p
          role="status"
          className={message === "Сохранено" ? "success-toast" : undefined}
        >
          {message === "Сохранено" && <FileCheck size={22} aria-hidden="true" />}
          {message}
        </p>
      )}
      {pending && (
        <p className="notice">
          Добавление места: <strong>{pending.name}</strong>. Создайте маршрут
          или откройте существующий. При сохранении место также попадёт в
          избранное.
        </p>
      )}
      {routesLoading && !route && <p role="status">Загрузка маршрутов…</p>}
      {!route && !routesLoading && (
        <>
          <div className="route-list">
            {routes.map((r) => (
              <div
                className={`panel route-list-item ${r.active ? "is-active" : ""}`}
                key={r.id}
              >
                <label className="route-active">
                  <input
                    type="radio"
                    name="active-itinerary"
                    value={r.id}
                    checked={r.active}
                    disabled={busy}
                    aria-label={`Активный маршрут: ${r.name}`}
                    onChange={async () => {
                      setBusy(true);
                      setError("");
                      try {
                        await api(`/itineraries/${r.id}/active?active=true`, {
                          method: "PUT",
                        });
                        setPage(1);
                        setRevision((v) => v + 1);
                        await open(r.id);
                      } catch (e) {
                        setError((e as Error).message);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  />
                  {r.active ? "Активный маршрут" : "Сделать активным"}
                </label>
                <button
                  className="route-open"
                  disabled={busy}
                  onClick={() => void open(r.id)}
                >
                  <strong>{r.name}</strong>
                  <small>
                    Создан {new Date(r.created_at).toLocaleDateString("ru-RU")}{" "}
                    · {r.stops.length} мест
                  </small>
                </button>
                <button
                  className="route-delete"
                  aria-label={`Удалить маршрут: ${r.name}`}
                  disabled={busy}
                  onClick={() => {
                    setDeleteError("");
                    setDeleteTarget(r);
                  }}
                >
                  <Trash2 size={17} />
                </button>
              </div>
            ))}
            <Button
              variant="outline"
              className="route-create-card"
              disabled={busy}
              aria-label="Создать маршрут"
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  const r = await api<Route>("/itineraries", {
                    method: "POST",
                    body: body({
                      name: `Маршрут ${new Date().toLocaleDateString("ru-RU")}`,
                      stops: pending
                        ? [
                            {
                              place_id: pending.id,
                              note: "",
                              status: "planned",
                            },
                          ]
                        : [],
                    }),
                  });
                  await api(`/itineraries/${r.id}/active?active=true`, {
                    method: "PUT",
                  });
                  setPage(1);
                  setRevision((v) => v + 1);
                  await open(r.id);
                  setMessage("Маршрут создан");
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <Plus size={36} aria-hidden="true" />
              <span>Новый маршрут</span>
            </Button>
          </div>
          {total > 30 && (
            <div className="pager">
              <button
                disabled={page === 1 || busy}
                onClick={() => setPage((v) => v - 1)}
              >
                Назад
              </button>
              <span>
                {page} / {Math.ceil(total / 30)}
              </span>
              <button
                disabled={page * 30 >= total || busy}
                onClick={() => setPage((v) => v + 1)}
              >
                Далее
              </button>
            </div>
          )}
        </>
      )}
      {route && (
        <section className="route-editor">
          <Button
            className="route-switch-button"
            variant="outline"
            disabled={busy}
            onClick={() => {
              setChoosing(true);
              setPage(1);
              setRoute(null);
              setEditing(false);
              setSelected(null);
              setMessage("");
              setError("");
            }}
          >
            <ListRestart size={16} /> Сменить активный маршрут или создать
          </Button>
          <div
            className={route.active ? "active-route-heading" : "route-heading"}
          >
            {route.active && (
              <p className="active-route-badge">Активный маршрут</p>
            )}
            <h2>{route.name}</h2>
          </div>
          <fieldset disabled={busy}>
            <div
              className="actions route-toolbar"
              role="group"
              aria-label="Управление маршрутом"
            >
              <Button
                variant="outline"
                type="button"
                className="route-settings-toggle"
                aria-expanded={editing}
                onClick={() => setEditing(!editing)}
              >
                {editing ? (
                  <ChevronUp size={16} aria-hidden="true" />
                ) : (
                  <Pencil size={16} aria-hidden="true" />
                )}
                {editing ? "Скрыть редактирование" : "Редактировать"}
              </Button>

              <Button onClick={() => void save()} disabled={!route.name.trim()}>
                <Save size={16} aria-hidden="true" />
                Сохранить маршрут
              </Button>

              <Button
                variant="ghost"
                onClick={() => {
                  setDeleteError("");
                  setDeleteTarget(route);
                }}
              >
                <Trash2 size={16} aria-hidden="true" />
                Удалить маршрут
              </Button>
            </div>

            <div
              className={editing ? "route-settings" : undefined}
              key={route.id}
            >
              {editing && (
                <div className="route-settings-fields">
                  <label>
                    Название маршрута
                    <input
                      value={route.name}
                      maxLength={120}
                      onChange={(e) =>
                        setRoute({ ...route, name: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    Дата поездки
                    <input
                      type="date"
                      value={route.trip_date || ""}
                      onChange={(e) =>
                        setRoute({
                          ...route,
                          trip_date: e.target.value || null,
                        })
                      }
                    />
                  </label>
                </div>
              )}
            </div>
            {pending && !route.stops.some((s) => s.place_id === pending.id) && (
              <Button
                disabled={route.stops.length >= 50}
                onClick={() =>
                  setRoute({
                    ...route,
                    stops: [
                      ...route.stops,
                      { place_id: pending.id, note: "", status: "planned" },
                    ],
                    items: [
                      ...(route.items || []),
                      {
                        place_id: pending.id,
                        note: "",
                        status: "planned",
                        place: pending,
                      },
                    ],
                  })
                }
              >
                Добавить выбранное место
              </Button>
            )}
            {!route.stops.length && (
              <p>
                Откройте место на карте и нажмите «Добавить в маршрутный лист».
              </p>
            )}
            {!!route.stops.length && (
              <div className="route-table-scroll">
                <table className="route-table">
                  <caption className="sr-only">Места маршрутного листа</caption>
                  <thead>
                    <tr>
                      <th scope="col">№</th>
                      <th scope="col" aria-sort={sortDirection === "asc" ? "ascending" : sortDirection === "desc" ? "descending" : "none"}>
                        <div className="route-place-sort">
                          Место
                          <button
                            type="button"
                            aria-label={sortDirection === "asc" ? "Сортировать места от Я до А" : "Сортировать места от А до Я"}
                            title={sortDirection === "asc" ? "От Я до А" : "От А до Я"}
                            onClick={() => sortPlaces(sortDirection === "asc" ? "desc" : "asc")}
                          >
                            <ArrowUpDown size={16} aria-hidden="true" />
                          </button>
                        </div>
                      </th>
                      <th scope="col">Статус</th>
                      <th scope="col">Карта</th>
                      <th scope="col">Действия</th>
                    </tr>
                  </thead>
                  <tbody>
                    {route.stops.map((s, i) => {
                      const p = route.items?.find(
                        (item) => item.place_id === s.place_id,
                      )?.place;
                      return (
                        <tr className="route-stop" key={s.place_id}>
                          <td>{i + 1}</td>
                          <td
                            className={p ? "route-place-cell" : ""}
                            onClick={() => {
                              if (p) setSelected(p);
                            }}
                          >
                            <h3>
                              {p ? (
                                <button onClick={() => setSelected(p)}>
                                  {p.name}
                                </button>
                              ) : (
                                "Место недоступно"
                              )}
                            </h3>
                            {p?.region && (
                              <small className="muted">{p.region}</small>
                            )}
                          </td>
                          <td>
                            <select
                              aria-label="Статус точки"
                              value={s.status}
                              onChange={(e) =>
                                updateStop(i, {
                                  status: e.target.value as Stop["status"],
                                })
                              }
                            >
                              <option value="planned">Планирую</option>
                              <option value="visited">Посетил</option>
                              <option value="skipped">Пропустил</option>
                            </select>
                          </td>
                          <td>
                            {p ? (
                              <a
                                className="button button-outline"
                                target="_blank"
                                rel="noopener noreferrer"
                                aria-label={`На карту: ${p.name}`}
                                href={`https://yandex.ru/maps/?pt=${p.longitude},${p.latitude}&z=16&l=map`}
                              >
                                На карту ↗
                              </a>
                            ) : (
                              "—"
                            )}
                          </td>
                          <td>
                            <div className="actions">
                              <button
                                aria-label={`Убрать место ${i + 1}`}
                                onClick={() =>
                                  setRoute({
                                    ...route,
                                    stops: route.stops.filter(
                                      (_, index) => i !== index,
                                    ),
                                  })
                                }
                              >
                                Убрать
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <div className="route-send-actions">
              <Button
                variant="outline"
                onClick={async () => {
                  if (!route) return;
                  setBusy(true);
                  setError("");
                  setMessage("");
                  try {
                    await api(`/itineraries/${route.id}`, {
                      method: "PUT",
                      body: body({
                        name: route.name,
                        trip_date: route.trip_date,
                        notes: route.notes,
                        stops: route.stops,
                        version: route.version,
                      }),
                    });
                    setRoute(await api<Route>(`/itineraries/${route.id}`));
                    setRevision((value) => value + 1);
                    await api(`/itineraries/${route.id}/telegram`, {
                      method: "POST",
                    });
                    setMessage("Маршрут отправлен в Telegram");
                  } catch (error) {
                    setError((error as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
                disabled={!route.name.trim()}
              >
                <Send size={16} /> В Telegram
              </Button>
            </div>
          </fieldset>
        </section>
      )}
      {selected && (
        <div className="detail-overlay">
          <PlaceDetail
            key={selected.id}
            fullscreen
            place={selected}
            onClose={() => setSelected(null)}
          />
        </div>
      )}
      {deleteTarget && (
        <dialog
          ref={deleteDialog}
          className="route-confirm"
          aria-labelledby="route-delete-title"
          onCancel={(event) => {
            event.preventDefault();
            if (!busy) setDeleteTarget(null);
          }}
        >
          <h2 id="route-delete-title">Удалить маршрут?</h2>
          <p>«{deleteTarget.name}»</p>
          {deleteError && (
            <p role="alert" className="notice">
              {deleteError}
            </p>
          )}
          <div className="actions">
            <Button
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setDeleteError("");
                try {
                  await api(`/itineraries/${deleteTarget.id}`, {
                    method: "DELETE",
                  });
                  if (route?.id === deleteTarget.id) {
                    setRoute(null);
                    setEditing(false);
                    setSelected(null);
                  }
                  if (routes.length === 1 && page > 1) setPage(page - 1);
                  setRevision((v) => v + 1);
                  setMessage("Маршрут удалён");
                  setDeleteTarget(null);
                } catch (e) {
                  setDeleteError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Да
            </Button>
            <Button
              variant="outline"
              autoFocus
              disabled={busy}
              onClick={() => setDeleteTarget(null)}
            >
              Нет
            </Button>
          </div>
        </dialog>
      )}
    </main>
  );
}
