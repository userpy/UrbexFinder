"use client";
import Image from "next/image";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useSession } from "@/entities/session";
import { Place, statuses } from "@/entities/place";
import { api, Page } from "@/shared/api";
import { PlaceForm } from "@/widgets/place-form";
import { PlaceDetail } from "@/widgets/place-detail";
import { Button } from "@/shared/ui/button";
type Item = Place & { text?: string; place_id?: number };
export function AccountView() {
  const { user, loading, logout, refresh } = useSession();
  const [tab, setTab] = useState("places"),
    [items, setItems] = useState<Item[]>([]),
    [error, setError] = useState(""),
    [page, setPage] = useState(1),
    [total, setTotal] = useState(0),
    [edit, setEdit] = useState<Place | null>(null),
    [selected, setSelected] = useState<Place | null>(null),
    [revision, setRevision] = useState(0);
  useEffect(() => {
    if (user) {
      api<Page<Item>>(`/me/${tab}?page=${page}`)
        .then((d) => {
          setError("");
          setItems(d.items);
          setTotal(d.total);
        })
        .catch((e) => setError(e.message));
    }
  }, [user, tab, page, revision]);
  if (loading) return <main className="page">Загрузка…</main>;
  if (!user)
    return (
      <main className="page">
        <h1>Личный кабинет</h1>
        <Link href="/login">Войти в аккаунт →</Link>
      </main>
    );
  return (
    <main className="page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">ЛИЧНЫЙ КАБИНЕТ</span>
          <h1>{user.name}</h1>
          <p className="muted">{user.email}</p>
        </div>
        <div className="actions">
          <Button
            variant="outline"
            onClick={() => logout().catch((e) => setError(e.message))}
          >
            Выйти
          </Button>
          <Button
            variant="ghost"
            onClick={async () => {
              try {
                await api("/auth/revoke-all", { method: "POST" });
                await refresh();
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            Завершить все сессии
          </Button>
        </div>
      </div>
      <div className="tabs">
        {Object.entries({
          places: "Мои заявки",
          photos: "Фотографии",
          reviews: "Отзывы",
          reports: "Жалобы",
        }).map(([v, l]) => (
          <button
            className={tab === v ? "active" : ""}
            key={v}
            onClick={() => {
              setTab(v);
              setPage(1);
              setEdit(null);
            }}
          >
            {l}
          </button>
        ))}
      </div>
      {error && (
        <p role="alert" className="notice">
          {error}
        </p>
      )}
      {edit ? (
        <div className="narrow">
          <Button variant="ghost" onClick={() => setEdit(null)}>
            Отмена
          </Button>
          <PlaceForm
            initial={edit}
            onSuccess={() => {
              setEdit(null);
              setRevision((v) => v + 1);
            }}
          />
        </div>
      ) : (
        <div className="account-grid">
          {items.map((i) => (
            <article className="panel" key={i.id}>
              <span className={`status ${i.status}`}>
                {statuses[i.status] || "Сохранено"}
              </span>
              <h2>{i.name || i.text || `Фотография #${i.id}`}</h2>
              {tab === "photos" && (
                <Image
                  unoptimized
                  width={720}
                  height={480}
                  className="account-photo"
                  src={`/api/photos/${i.id}/content`}
                  alt="Моя фотография"
                />
              )}
              {i.reason && (
                <p className="notice">Решение модератора: {i.reason}</p>
              )}
              {tab === "places" &&
                ["rejected", "changes_requested"].includes(i.status) && (
                  <Button onClick={() => setEdit(i)}>
                    Исправить и отправить снова
                  </Button>
                )}
              {tab === "places" && (
                <Button variant="outline" onClick={() => setSelected(i)}>
                  Открыть карточку
                </Button>
              )}
            </article>
          ))}
        </div>
      )}
      {!items.length && !error && (
        <div className="empty">
          <h2>Здесь появятся ваши находки</h2>
          <Link href="/submit">Предложить первое место →</Link>
        </div>
      )}
      <div className="pager">
        <button disabled={page === 1} onClick={() => setPage((v) => v - 1)}>
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
      {selected && (
        <div className="detail-overlay">
          <PlaceDetail
            key={selected.id}
            place={selected}
            onClose={() => setSelected(null)}
          />
        </div>
      )}
    </main>
  );
}
