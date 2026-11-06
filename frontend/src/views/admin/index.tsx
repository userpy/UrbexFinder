"use client";
import { CategoryIconPicker } from "./category-icon-picker";
import { DeleteReview } from "@/widgets/place-detail";
import { DeletePlaceDialog } from "./delete-place-dialog";
import { DeleteUserDialog } from "./delete-user-dialog";
import { Ban, Trash2, Unlock } from "lucide-react";
import Image from "next/image";
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSession } from "@/entities/session";
import { Place, Category, statuses, CategoryIcon } from "@/entities/place";
import { api, body, Page } from "@/shared/api";
import { HighlightMatch, descriptionExcerpt } from "@/shared/ui/highlight-match";
import { Button } from "@/shared/ui/button";
import { MapPanel } from "@/widgets/map";
type Row = Partial<Place> & {
  id: number;
  icon?: string | null;
  email?: string;
  role?: string;
  blocked?: boolean;
  active?: boolean;
  text?: string;
  place_id?: number;
  target_type?: string;
  target_id?: number;
  action?: string;
  target?: string;
  detail?: string;
  actor_id?: number;
};
const labels: Record<string, string> = {
  overview: "Обзор",
  queue: "Очередь мест",
  photos: "Фотографии",
  places: "Все места",
  users: "Пользователи",
  reviews: "Отзывы",
  reports: "Жалобы",
  categories: "Категории",
};
export function AdminView() {
  const { user, loading } = useSession();
  const [search, setSearch] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [deletePlace, setDeletePlace] = useState(false);
  const [deleteReview, setDeleteReview] = useState(false);
  const [deleteUser, setDeleteUser] = useState(false);
  const inspector = useRef<HTMLDialogElement>(null);
  const [placeName, setPlaceName] = useState("");
  const [description, setDescription] = useState("");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [placeCategory, setPlaceCategory] = useState("");
  const [placeCategories, setPlaceCategories] = useState<Category[]>([]);
  const [address, setAddress] = useState("");
  const validCoordinates =
    latitude.trim() !== "" &&
    longitude.trim() !== "" &&
    Number.isFinite(Number(latitude)) &&
    Number.isFinite(Number(longitude)) &&
    Math.abs(Number(latitude)) <= 85 &&
    Math.abs(Number(longitude)) <= 180;
  const draftBounds = useMemo<[number, number, number, number] | undefined>(
    () =>
      validCoordinates
        ? [
            Number(longitude) - 0.005,
            Number(latitude) - 0.005,
            Number(longitude) + 0.005,
            Number(latitude) + 0.005,
          ]
        : undefined,
    [latitude, longitude, validCoordinates],
  );
  const [savedMessage, setSavedMessage] = useState("");
  const [tab, setTab] = useState("overview"),
    [rows, setRows] = useState<Row[]>([]),
    [total, setTotal] = useState(0),
    [page, setPage] = useState(1),
    [error, setError] = useState(""),
    [selected, setSelected] = useState<Row | null>(null),
    [reason, setReason] = useState(""),
    [revision, setRevision] = useState(0),
    [stats, setStats] = useState<Record<string, number>>({}),
    [photos, setPhotos] = useState<Row[]>([]),
    [busy, setBusy] = useState(false),
    [place, setPlace] = useState<Place | null>(null);
  useEffect(() => {
    if (selected && !inspector.current?.open) inspector.current?.showModal();
  }, [selected]);
  const kind = tab === "queue" ? "places" : tab;
  useEffect(() => {
    if (!user || user.role === "user") return;
    if (tab === "overview") {
      Promise.all(
        ["places", "photos", "reports", "reviews"].map(
          async (k) =>
            [
              k,
              (await api<Page<Row>>(`/admin/${k}?status=pending`)).total,
            ] as const,
        ),
      )
        .then((v) => {
          setError("");
          setStats(Object.fromEntries(v));
        })
        .catch((e) => {
          if (e.name !== "AbortError") setError(e.message);
        });
    } else
      api<Page<Row>>(
        `/admin/${kind}?page=${page}${tab === "places" ? `&q=${encodeURIComponent(searchQuery)}` : ""}${["queue", "photos", "reports"].includes(tab) ? "&status=pending" : ""}`,
      )
        .then((d) => {
          setError("");
          setRows(d.items);
          setTotal(d.total);
        })
        .catch((e) => {
          if (e.name !== "AbortError") setError(e.message);
        });
  }, [user, tab, kind, page, revision, searchQuery]);
  useEffect(() => {
    if (!selected) return;
    const abort = new AbortController();
    if (kind === "places") {
      api<Page<Category>>("/categories", { signal: abort.signal })
        .then((result) => setPlaceCategories(result.items))
        .catch((e) => { if (e.name !== "AbortError") setError(e.message); });
    }
    const id = kind === "places" ? selected.id : selected.place_id;
    if (id) {
      api<Place>(`/places/${id}`, { signal: abort.signal })
        .then((p) => {
          setPlace(p);
          setPlaceCategory(String(p.category_id));
          setPlaceName(p.name);
          setDescription(p.description || "");
          setLatitude(String(p.latitude));
          setLongitude(String(p.longitude));
          setAddress(p.full_address || p.region || "");
        })
        .catch((e) => {
          if (e.name !== "AbortError") setError(e.message);
        });
      if (kind !== "reviews") api<Page<Row>>(`/admin/photos?place_id=${id}`, { signal: abort.signal })
        .then((result) => setPhotos(result.items))
        .catch((e) => {
          if (e.name !== "AbortError") setError(e.message);
        });
    }
    return () => abort.abort();
  }, [selected, kind]);
  async function mutate(path: string, data: unknown, method = "POST") {
    setBusy(true);
    setError("");
    try {
      await api(path, { method, body: body(data) });
      setRevision((v) => v + 1);
      setSelected(null);
      setReason("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (loading) return <main className="page">Загрузка…</main>;
  if (!user || user.role === "user")
    return (
      <main className="page">
        <h1>Доступ ограничен</h1>
        <p>Раздел доступен модераторам и администраторам.</p>
        <Link href="/">Вернуться на карту</Link>
      </main>
    );
  return (
    <main className="admin-layout">
      <aside className="admin-nav">
        <div className="eyebrow">РАБОЧЕЕ ПРОСТРАНСТВО</div>
        <h2>Управление</h2>
        {Object.entries(labels)
          .filter(
            ([k]) =>
              user.role === "admin" ||
              !["users", "categories"].includes(k),
          )
          .map(([k, l]) => (
            <button
              className={tab === k ? "active" : ""}
              key={k}
              onClick={() => {
                setTab(k);
                setPage(1);
                setSelected(null);
              }}
            >
              {l}
            </button>
          ))}
      </aside>
      <div className="admin-content">
        <div className="eyebrow">
          URBEXFINDER / {user.role === "admin" ? "АДМИНИСТРАТОР" : "МОДЕРАТОР"}
        </div>
        <h1>{labels[tab]}</h1>
        {error && (
          <p className="notice" role="alert">
            {error}
          </p>
        )}
        {tab === "overview" ? (
          <>
            <p className="muted">Заявки, ожидающие решения</p>
            <div className="stat-grid">
              {Object.entries(stats).map(([k, n]) => (
                <button
                  className="panel stat"
                  key={k}
                  onClick={() => setTab(k === "places" ? "queue" : k)}
                >
                  <span>{labels[k]}</span>
                  <strong>{n}</strong>
                  <small>Открыть очередь →</small>
                </button>
              ))}
            </div>
          </>
        ) : (
          <>
            {tab === "places" && (
              <form className="inline-form" onSubmit={(event) => {
                event.preventDefault(); setPage(1); setSearchQuery(search.trim());
              }}>
                <input aria-label="Поиск мест" placeholder="Название, адрес или описание" value={search}
                  maxLength={200} onChange={(event) => setSearch(event.target.value)} />
                <Button type="submit">Найти</Button>
                {(search || searchQuery) && <Button type="button" variant="ghost" onClick={() => {
                  setSearch(""); setSearchQuery(""); setPage(1);
                }}>Сбросить ×</Button>}
              </form>
            )}
            {tab === "categories" && (
              <Button onClick={() => {
                setError("");
                setSavedMessage("");
                setPlace(null);
                setPhotos([]);
                setSelected({ id: 0, name: "", active: true, icon: null });
              }}>Добавить категорию</Button>
            )}
            <div className="admin-table">
              <div className="table-head">
                <span>ОБЪЕКТ / ЗАПИСЬ</span>
                <span>СОСТОЯНИЕ</span>
                <span>ID</span>
              </div>
              {rows.map((r) => (
                <button
                  className="table-row"
                  key={r.id}
                  onClick={() => {
                    setSavedMessage("");
                    setError("");
                    setPhotos([]);
                    setPlace(null);
                    setSelected(r);
                    setReason("");
                  }}
                >
                  <span>
                    <strong>
                      {kind === "categories" && <CategoryIcon category={r.name} icon={r.icon} />}
                      <HighlightMatch
                        text={r.name || r.email || r.text || r.action || `Фото #${r.id}`}
                        query={tab === "places" ? searchQuery : ""}
                      />
                    </strong>
                    <small>
                      <HighlightMatch text={r.full_address || r.region || r.target || r.target_type || ""}
                        query={tab === "places" ? searchQuery : ""} />
                    </small>
                    {tab === "places" && searchQuery && r.description && (
                      <small className="admin-search-excerpt">
                        <HighlightMatch text={descriptionExcerpt(r.description, searchQuery)} query={searchQuery} />
                      </small>
                    )}
                  </span>
                  <span>
                    {statuses[r.status || ""] ||
                      r.role ||
                      (r.active === false ? "Выключена" : "—")}
                  </span>
                  <span>#{r.id}</span>
                </button>
              ))}
              {!rows.length && (
                <div className="empty">Нет записей в этой очереди</div>
              )}
            </div>
            <div className="pager">
              <button
                disabled={page === 1}
                onClick={() => setPage((v) => v - 1)}
              >
                Назад
              </button>
              <span>
                {page} · Всего {total}
              </span>
              <button
                disabled={page * 30 >= total}
                onClick={() => setPage((v) => v + 1)}
              >
                Далее
              </button>
            </div>
          </>
        )}
        {selected && (
          <dialog
            ref={inspector}
            className={`admin-inspector${kind === "categories" ? " category-inspector" : ""}`}
            aria-labelledby="inspector-title"
            onCancel={(event) => {
              if (busy) event.preventDefault();
              else setSelected(null);
            }}
          >
            <div className="page-heading">
              <h2 id="inspector-title">
                {(kind === "places" ? place?.name : null) ||
                  selected.name ||
                  selected.email ||
                  (kind === "categories" && selected.id === 0 ? "Новая категория" : `Запись #${selected.id}`)}
              </h2>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => setSelected(null)}
              >
                Закрыть ×
              </Button>
            </div>
            {error && (
              <p role="alert" className="notice">
                {error}
              </p>
            )}
            {savedMessage && <p role="status">{savedMessage}</p>}
            {place && kind !== "reviews" && (
              <>
                {kind === "places" ? (
                  <form
                    onSubmit={async (event) => {
                      event.preventDefault();
                      setBusy(true);
                      setError("");
                      setSavedMessage("");
                      try {
                        const updated = await api<Place>(
                          `/admin/places/${place.id}`,
                          {
                            method: "PATCH",
                            body: body({
                              name: placeName.trim(),
                              description,
                              latitude: Number(latitude),
                              longitude: Number(longitude),
                              address,
                              category_id: Number(placeCategory),
                              expected_updated_at: place.updated_at,
                            }),
                          },
                        );
                        setPlace(updated);
                        setPlaceName(updated.name);
                        setDescription(updated.description);
                        setRevision((v) => v + 1);
                        setSavedMessage("Изменения сохранены");
                      } catch (error) {
                        setError((error as Error).message);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    <label>
                      Название места
                      <input
                        value={placeName}
                        onChange={(event) => setPlaceName(event.target.value)}
                        minLength={3}
                        maxLength={200}
                        required
                        disabled={busy}
                      />
                    </label>
                    <label>
                      Описание места
                      <textarea
                        value={description}
                        onChange={(event) => setDescription(event.target.value)}
                        required
                        maxLength={20000}
                        rows={8}
                        disabled={busy}
                      />
                    </label>
                    <p className="muted">
                      Перетащите метку на карте — широта и долгота обновятся автоматически.
                    </p>
                <div className="review-map">
                  <MapPanel
                    key={place.id}
                    places={[
                      kind === "places" && validCoordinates
                        ? {
                            ...place,
                            latitude: Number(latitude),
                            longitude: Number(longitude),
                          }
                        : place,
                    ]}
                    selected={place.id}
                    center={[place.longitude, place.latitude]}
                    focusBounds={kind === "places" ? draftBounds : undefined}
                    onSelect={() => {}}
                    editable={kind === "places"}
                    markerDisabled={busy}
                    pointHint={
                      kind === "places"
                        ? "Перетащите метку, чтобы изменить координаты"
                        : undefined
                    }
                    onPoint={
                      kind === "places"
                        ? (lon, lat) => {
                            if (!busy) {
                              setLatitude(lat.toFixed(6));
                              setLongitude(lon.toFixed(6));
                              setSavedMessage(
                                "Точка изменена. При необходимости обновите адрес и сохраните изменения.",
                              );
                            }
                          }
                        : undefined
                    }
                  />
                </div>
                    <div className="form-grid">
                      <label>
                        Широта
                        <input
                          type="number"
                          step="any"
                          min="-85"
                          max="85"
                          value={latitude}
                          readOnly
                          required
                          disabled={busy}
                        />
                      </label>
                      <label>
                        Долгота
                        <input
                          type="number"
                          step="any"
                          min="-180"
                          max="180"
                          value={longitude}
                          readOnly
                          required
                          disabled={busy}
                        />
                      </label>
                    </div>
                    <label>
                      Категория
                      <select value={placeCategory} onChange={(e) => setPlaceCategory(e.target.value)} disabled={busy} required>
                        {!placeCategories.some((c) => String(c.id) === placeCategory) && (
                          <option value={placeCategory}>{place.category || "Текущая категория"}</option>
                        )}
                        {placeCategories.map((category) => (
                          <option key={category.id} value={category.id}>{category.name}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Адрес
                      <input
                        value={address}
                        readOnly
                        required
                        maxLength={2000}
                        disabled={busy}
                      />
                    </label>
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={busy || !validCoordinates}
                      onClick={async () => {
                        setBusy(true);
                        setError("");
                        setSavedMessage("");
                        try {
                          const result = await api<{ address: string }>(
                            `/admin/geocode/reverse?${new URLSearchParams({ latitude, longitude })}`,
                          );
                          setAddress(result.address);
                          setSavedMessage(
                            "Адрес обновлён в форме. Нажмите «Сохранить изменения».",
                          );
                        } catch (error) {
                          setError((error as Error).message);
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      Обновить адрес по координатам
                    </Button>
                    <small>
                      Адрес: ©{" "}
                      <a
                        href="https://www.openstreetmap.org/copyright"
                        target="_blank"
                        rel="noreferrer"
                      >
                        OpenStreetMap
                      </a>
                      . Проверьте найденный адрес перед сохранением.
                    </small>
                    <Button
                      disabled={
                        busy ||
                        placeName.trim().length < 3 ||
                        !description.trim() ||
                        !address.trim() ||
                        !validCoordinates
                      }
                    >
                      Сохранить изменения
                    </Button>
                    {tab === "places" && (
                      <Button type="button" variant="outline" disabled={busy} onClick={() => setDeletePlace(true)}>
                        <Trash2 size={16} /> Удалить место
                      </Button>
                    )}
                    {deletePlace && (
                      <DeletePlaceDialog id={place.id} name={place.name}
                        onClose={() => setDeletePlace(false)}
                        onDeleted={() => {
                          setDeletePlace(false); setSelected(null); setPlace(null);
                          setRevision((value) => value + 1);
                        }} />
                    )}
                  </form>
                ) : (
                  <p>{place.description}</p>
                )}
                {tab !== "places" && (
                  <>
                <p className="muted">
                  Регион: {place.region} · Состояние: {place.condition} · Автор:{" "}
                  {place.author_id || "Импорт из бота"}
                </p>
                <p className="notice">Доступ: {place.access}</p>
                {kind !== "places" && (
                <div className="review-map">
                  <MapPanel
                    key={place.id}
                    places={[
                      kind === "places" && validCoordinates
                        ? {
                            ...place,
                            latitude: Number(latitude),
                            longitude: Number(longitude),
                          }
                        : place,
                    ]}
                    selected={place.id}
                    center={[place.longitude, place.latitude]}
                    focusBounds={kind === "places" ? draftBounds : undefined}
                    onSelect={() => {}}
                    editable={kind === "places"}
                    markerDisabled={busy}
                    pointHint={
                      kind === "places"
                        ? "Перетащите метку, чтобы изменить координаты"
                        : undefined
                    }
                    onPoint={
                      kind === "places"
                        ? (lon, lat) => {
                            if (!busy) {
                              setLatitude(lat.toFixed(6));
                              setLongitude(lon.toFixed(6));
                              setSavedMessage(
                                "Точка изменена. При необходимости обновите адрес и сохраните изменения.",
                              );
                            }
                          }
                        : undefined
                    }
                  />
                </div>
                )}
                <p className="coords">
                  {kind === "places" ? latitude : place.latitude},{" "}
                  {kind === "places" ? longitude : place.longitude}
                </p>
                  </>
                )}
              </>
            )}
            {selected.text && <p style={{ whiteSpace: "pre-wrap" }}>{selected.text}</p>}
            {kind === "reviews" && selected.place_id && (
              <p>
                <a href={`/?place=${selected.place_id}`}>
                  {place?.name || `Открыть место #${selected.place_id}`} →
                </a>
              </p>
            )}
            {kind === "reviews" && (
              <>
                <Button variant="outline" onClick={() => setDeleteReview(true)}>
                  <Trash2 size={16} /> Удалить
                </Button>
                {deleteReview && (
                  <DeleteReview
                    id={selected.id}
                    onClose={() => setDeleteReview(false)}
                    onDeleted={() => {
                      setDeleteReview(false);
                      setSelected(null);
                      setRevision((value) => value + 1);
                    }}
                  />
                )}
              </>
            )}
            {tab !== "places" && kind !== "reviews" && selected.reason && (
              <p className="notice">Предыдущее решение: {selected.reason}</p>
            )}
            {selected.target_type && (
              <p>
                Объект жалобы: {selected.target_type} #{selected.target_id}
              </p>
            )}
            {kind === "photos" && (
              <Image
                unoptimized
                width={720}
                height={480}
                className="moderation-photo"
                src={`/api/photos/${selected.id}/content`}
                alt="Фотография на проверке"
              />
            )}
            {kind !== "reviews" && photos.length > 0 && (
              <div className="moderation-photos">
                {photos.map((p) => (
                  <div key={p.id}>
                    <Image
                      unoptimized
                      width={720}
                      height={480}
                      src={`/api/photos/${p.id}/content`}
                      alt={`Фото #${p.id}`}
                    />
                    <small>{statuses[p.status || ""]}</small>
                  </div>
                ))}
              </div>
            )}
            {tab !== "places" && ["places", "photos", "reports"].includes(kind) && (
              <>
                <label>
                  Причина решения
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Обязательно для отклонения и возврата"
                    maxLength={4000}
                  />
                </label>
                <div className="actions">
                  {[
                    [
                      "published",
                      kind === "reports"
                        ? "Жалоба рассмотрена"
                        : "Опубликовать",
                    ],
                    ["changes_requested", "На доработку"],
                    ["rejected", "Отклонить"],
                  ].map(([status, label]) => (
                    <Button
                      variant={status === "published" ? "default" : "outline"}
                      key={status}
                      disabled={
                        busy ||
                        (status !== "published" && reason.trim().length < 5)
                      }
                      onClick={() =>
                        mutate(`/admin/${kind}/${selected.id}/decision`, {
                          status,
                          reason,
                        })
                      }
                    >
                      {label}
                    </Button>
                  ))}
                </div>
              </>
            )}
            {kind === "users" && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  const f = new FormData(e.currentTarget);
                  mutate(
                    `/admin/users/${selected.id}`,
                    { role: f.get("role"), blocked: !!selected.blocked },
                    "PUT",
                  );
                }}
              >
                <label>
                  Роль
                  <select name="role" defaultValue={selected.role}>
                    <option value="user">Пользователь</option>
                    <option value="moderator">Модератор</option>
                    <option value="admin">Администратор</option>
                  </select>
                </label>
                <Button disabled={busy || selected.id === user.id}>
                  Сохранить роль
                </Button>
                <div className="actions">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busy || selected.id === user.id}
                    onClick={() =>
                      mutate(
                        `/admin/users/${selected.id}`,
                        { role: selected.role, blocked: !selected.blocked },
                        "PUT",
                      )
                    }
                  >
                    {selected.blocked ? (
                      <Unlock size={16} />
                    ) : (
                      <Ban size={16} />
                    )}
                    {selected.blocked ? "Разблокировать" : "Заблокировать"}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={busy || selected.id === user.id}
                    onClick={() => setDeleteUser(true)}
                  >
                    <Trash2 size={16} />
                    Удалить пользователя
                  </Button>
                </div>
                {deleteUser && (
                  <DeleteUserDialog
                    id={selected.id}
                    name={selected.name || selected.email || `#${selected.id}`}
                    onClose={() => setDeleteUser(false)}
                    onDeleted={() => {
                      setDeleteUser(false);
                      setSelected(null);
                      setRevision((v) => v + 1);
                    }}
                  />
                )}
              </form>
            )}
            {kind === "categories" && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  const f = new FormData(e.currentTarget);
                  mutate(
                    selected.id ? `/admin/categories/${selected.id}` : "/admin/categories",
                    { name: f.get("name"), active: f.get("active") === "on", icon: f.get("icon") || null },
                    selected.id ? "PUT" : "POST",
                  );
                }}
              >
                <label>
                  Название
                  <input
                    name="name"
                    defaultValue={selected.name}
                    minLength={2}
                    maxLength={100}
                    required
                  />
                </label>
                <CategoryIconPicker value={selected.icon} category={selected.name}
                  onChange={(icon) => setSelected({ ...selected, icon })} />
                <label className="checkbox">
                  <input
                    name="active"
                    type="checkbox"
                    defaultChecked={selected.active}
                  />
                  Доступна для новых мест
                </label>
                <Button disabled={busy}>Сохранить</Button>
              </form>
            )}
          </dialog>
        )}
      </div>
    </main>
  );
}
