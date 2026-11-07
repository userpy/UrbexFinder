"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { useSession } from "@/entities/session";
import { Place, statuses } from "@/entities/place";
import { api, Page } from "@/shared/api";
import { PlaceDetail } from "@/widgets/place-detail";
import { Button } from "@/shared/ui/button";
function DeleteOwnPlace({
  place,
  onClose,
  onDeleted,
}: {
  place: Place;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="route-confirm"
      aria-labelledby="delete-own-place-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
    >
      <h2 id="delete-own-place-title">Удалить место?</h2>
      <p>
        «{place.name}» исчезнет из ваших списков и не будет отображаться на
        карте.
      </p>
      {error && (
        <p role="alert" className="notice">
          {error}
        </p>
      )}
      <div className="actions">
        <Button variant="outline" autoFocus disabled={busy} onClick={onClose}>
          Отмена
        </Button>
        <Button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError("");
            try {
              await api(`/places/${place.id}`, { method: "DELETE" });
              onDeleted();
            } catch (e) {
              setError((e as Error).message);
              setBusy(false);
            }
          }}
        >
          {busy ? "Удаление…" : "Удалить место"}
        </Button>
      </div>
    </dialog>
  );
}

function PlacesList({
  status,
  onSelect,
}: {
  status: "published" | "pending";
  onSelect: (place: Place) => void;
}) {
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [deleting, setDeleting] = useState<Place | null>(null);
  const [data, setData] = useState<Page<Place> | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    api<Page<Place>>(`/me/places?status=${status}&page=${page}`)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [status, page, revision]);
  function changePage(next: number) {
    setData(null);
    setError("");
    setPage(next);
  }
  if (error)
    return (
      <p role="alert" className="notice">
        {error}
      </p>
    );
  if (!data) return <p role="status">Загрузка…</p>;
  return (
    <>
      {!data.items.length && (
        <p className="muted account-list-empty">Список пуст</p>
      )}
      {data.items.length > 0 && (
        <div className="account-table-scroll">
          <table
            className="account-places-table"
            aria-label={
              status === "pending" ? "Места на модерации" : "Мои места"
            }
          >
            <thead>
              <tr>
                <th scope="col">Название</th>
                <th scope="col">Статус</th>
                <th scope="col">Действия</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((place) => (
                <tr key={place.id}>
                  <td>{place.name}</td>
                  <td>
                    <span className={`status ${place.status}`}>
                      {statuses[place.status]}
                    </span>
                  </td>
                  <td className="account-place-actions">
                    <Button
                      variant="outline"
                      className="account-place-view"
                      onClick={() => onSelect(place)}
                    >
                      Открыть карточку
                    </Button>
                    <Button
                      variant="outline"
                      className="account-place-delete"
                      onClick={() => setDeleting(place)}
                    >
                      Удалить место
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {deleting && (
        <DeleteOwnPlace
          place={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            setDeleting(null);
            if (data.items.length === 1 && page > 1) setPage(page - 1);
            setData(null);
            setRevision((value) => value + 1);
          }}
        />
      )}
      {(data.total > 30 || page > 1) && (
        <div className="pager">
          <button disabled={page === 1} onClick={() => changePage(page - 1)}>
            Назад
          </button>
          <span>
            {page} · Всего {data.total}
          </span>
          <button
            disabled={page * 30 >= data.total}
            onClick={() => changePage(page + 1)}
          >
            Далее
          </button>
        </div>
      )}
    </>
  );
}

function PlacesSection({
  title,
  status,
  onSelect,
}: {
  title: string;
  status: "published" | "pending";
  onSelect: (place: Place) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="account-place-section"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>{title}</summary>
      {open && <PlacesList status={status} onSelect={onSelect} />}
    </details>
  );
}

export function AccountView() {
  const { user, loading, logout } = useSession();
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Place | null>(null);
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
      <div className="page-heading account-profile">
        <div>
          <span className="eyebrow">ЛИЧНЫЙ КАБИНЕТ</span>
          <div className="account-profile-title">
            <Link
              href="/"
              className="routes-back-map"
              aria-label="Вернуться к карте"
              title="Вернуться к карте"
            >
              <ArrowLeft size={24} aria-hidden="true" />
            </Link>
            <h1>{user.name}</h1>
          </div>
          <p className="muted">{user.email}</p>
        </div>
        <div className="actions">
          <Button
            variant="outline"
            onClick={() => logout().catch((e) => setError(e.message))}
          >
            Выйти
          </Button>
        </div>
      </div>
      {error && (
        <p role="alert" className="notice">
          {error}
        </p>
      )}
      <PlacesSection
        key={`${user.id}-published`}
        title="Мои места"
        status="published"
        onSelect={setSelected}
      />
      <PlacesSection
        key={`${user.id}-pending`}
        title="Места на модерации"
        status="pending"
        onSelect={setSelected}
      />
      {selected && (
        <PlaceDetail
          key={selected.id}
          place={selected}
          fullscreen
          onClose={() => setSelected(null)}
        />
      )}
    </main>
  );
}
