"use client";
import { DeleteReview } from "./delete-review";
export { DeleteReview } from "./delete-review";
import { ReportDialog } from "./report-dialog";
import { PhotoGallery } from "./gallery";
import { PlacePhoto } from "./telegram-photo";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import {
  X,
  Bookmark,
  Camera,
  MapPin,
  Flag,
  Maximize2,
  Minimize2,
  Copy,
  ExternalLink,
} from "lucide-react";
import {
  Place,
  Photo,
  Review,
  conditions,
  CategoryIcon,
} from "@/entities/place";
import { useSession } from "@/entities/session";
import { api, Page } from "@/shared/api";
import { Button } from "@/shared/ui/button";
export function PlaceDetail({
  place,
  onClose,
  fullscreen = false,
}: {
  place: Place;
  onClose: () => void;
  fullscreen?: boolean;
}) {
  const { user } = useSession();
  const [deleteReview, setDeleteReview] = useState<number | null>(null);
  const [reportTarget, setReportTarget] = useState<{
    type: "places" | "reviews";
    id: number;
  } | null>(null);
  const [copyNotice, setCopyNotice] = useState("");
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (copyTimer.current) clearTimeout(copyTimer.current);
    },
    [],
  );

  const [membership, setMembership] = useState<{
    id: number;
    added: boolean;
  } | null>(null);
  const added = membership?.id === place.id && membership.added;
  const [expanded, setExpanded] = useState(fullscreen);
  const dialog = useRef<HTMLDialogElement>(null);
  const expandButton = useRef<HTMLButtonElement>(null);
  const restoreFocus = useCallback(() => expandButton.current?.focus(), []);
  useEffect(() => {
    if (!expanded) return;
    dialog.current?.showModal();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = overflow;
      requestAnimationFrame(restoreFocus);
    };
  }, [expanded, restoreFocus]);
  const [photos, setPhotos] = useState<Photo[]>([]),
    [reviews, setReviews] = useState<Review[]>([]),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const [reviewPage, setReviewPage] = useState(1),
    [reviewTotal, setReviewTotal] = useState(0);
  useEffect(() => {
    if (!user) return;
    const abort = new AbortController();
    api<{ added: boolean }>(`/places/${place.id}/itinerary`, {
      signal: abort.signal,
    })
      .then((result) => setMembership({ id: place.id, added: result.added }))
      .catch((error) => {
        if (!abort.signal.aborted) setMessage(error.message);
      });
    return () => abort.abort();
  }, [place.id, user]);
  useEffect(() => {
    api<Page<Photo>>(`/places/${place.id}/photos`)
      .then((d) => setPhotos(d.items))
      .catch((e) => setMessage(e.message));
  }, [place.id]);
  useEffect(() => {
    api<Page<Review>>(
      `/places/${place.id}/reviews?source=telegram&page=${reviewPage}`,
    )
      .then((d) => {
        setReviews(d.items);
        setReviewTotal(d.total);
      })
      .catch((e) => setMessage(e.message));
  }, [place.id, reviewPage]);
  const content = (
    <aside className="detail">
      <div className="detail-top">
        <span className="eyebrow">
          ОБЪЕКТ / {String(place.id).padStart(5, "0")}
        </span>
        <button
          ref={expandButton}
          className="detail-expand"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
          {expanded ? "Свернуть" : "Во весь экран"}
        </button>
        <button aria-label="Закрыть карточку" onClick={onClose}>
          <X size={19} />
        </button>
      </div>
      {expanded ? (
        <PhotoGallery
          key={place.id}
          photos={photos}
          name={place.name}
          canDelete={!!user && ["admin", "moderator"].includes(user.role)}
          onDeleted={(id) => setPhotos((items) => items.filter((photo) => photo.id !== id))}
        />
      ) : (
        <>
          <div className="photo-cover">
            {photos.length ? (
              <PlacePhoto
                key={photos[0].id}
                id={photos[0].id}
                alt={place.name}
              />
            ) : (
              <>
                <Camera size={36} />
                <span>Фотографии пока не добавлены</span>
              </>
            )}
            <span className="photo-badge">{conditions[place.condition]}</span>
          </div>
          {photos[0]?.id < 0 && (
            <small className="telegram-photo-source">Фото из Telegram</small>
          )}
        </>
      )}
      <div className="detail-body">
        <h2>{place.name}</h2>
        {place.category && (
          <p className="muted location">
            <CategoryIcon category={place.category} icon={place.category_icon} width={18} height={18} />
            {place.category}
          </p>
        )}
        <p className="muted location">
          <MapPin size={14} />
          {place.region}
        </p>
        {expanded && (
        <div className="place-coordinates">
          <div
            className={`coords${copyNotice === "Скопировано" ? " coords-copied" : ""}`}
          >
            {place.latitude?.toFixed(5) ?? "—"}° N &nbsp;{" "}
            {place.longitude?.toFixed(5) ?? "—"}° E
          </div>
          {Number.isFinite(place.latitude) &&
            Number.isFinite(place.longitude) && (
              <div className="coordinate-actions">
                <button
                  type="button"
                  aria-label="Скопировать координаты"
                  onClick={async () => {
                    if (copyTimer.current) clearTimeout(copyTimer.current);
                    try {
                      await navigator.clipboard.writeText(
                        `${place.latitude}, ${place.longitude}`,
                      );
                      setCopyNotice("Скопировано");
                      copyTimer.current = setTimeout(
                        () => setCopyNotice(""),
                        2200,
                      );
                    } catch {
                      setCopyNotice("Не удалось скопировать");
                      copyTimer.current = setTimeout(
                        () => setCopyNotice(""),
                        3500,
                      );
                    }
                  }}
                >
                  <Copy size={14} />
                  Скопировать
                </button>
                <span
                  className={
                    copyNotice === "Скопировано"
                      ? "sr-only"
                      : "coordinate-copy-notice"
                  }
                  role="status"
                >
                  {copyNotice}
                </span>
                <a
                  href={`https://yandex.ru/maps/?pt=${place.longitude},${place.latitude}&z=16&l=map`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <ExternalLink size={14} />
                  На карту
                </a>
              </div>
            )}
        </div>
        )}
        {user ? (
          <Button
            variant="outline"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setMessage("");
              try {
                if (added) {
                  await api(`/places/${place.id}/itinerary`, {
                    method: "DELETE",
                  });
                  setMembership({ id: place.id, added: false });
                  setMessage("Место удалено из маршрутного листа");
                  return;
                }
                const result = await api<{
                  name: string;
                  already_added: boolean;
                }>(`/places/${place.id}/itinerary`, { method: "POST" });
                setMembership({ id: place.id, added: true });
                setMessage(
                  result.already_added
                    ? `Место уже есть в маршруте «${result.name}»`
                    : `Добавлено в маршрут «${result.name}»`,
                );
              } catch (error) {
                setMessage((error as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <Bookmark size={15} />
            {added
              ? "Удалить из маршрутного листа"
              : "Добавить в маршрутный лист"}
          </Button>
        ) : (
          <p className="muted">
            <Link href="/login">Войдите</Link>, чтобы добавить место в
            маршрутный лист.
          </p>
        )}
        <section>
          <h3>Об объекте</h3>
          <p className="preserve">{place.description}</p>
        </section>
        {expanded && reviewTotal > 0 && (
          <section>
            <h3>
              Отзывы из Telegram{" "}
              {reviewTotal > 0 && <span className="muted">{reviewTotal}</span>}
            </h3>
            {reviews.map((r) => (
                <article className="review" key={r.id}>
                  <small>
                    {r.source === "telegram"
                      ? `${r.author_name || "Участник"} · Telegram`
                      : `Исследователь #${r.author_id}`}{" "}
                    {r.score != null && `· ${r.score}/5`}
                  </small>
                  <p>{r.text}</p>
                  {user && ["admin", "moderator"].includes(user.role) && (
                    <button
                      className="text-button"
                      onClick={() => setDeleteReview(r.id)}
                    >
                      Удалить комментарий
                    </button>
                  )}
                </article>
              ))}
            {reviewTotal > 30 && (
              <div className="pager">
                <button
                  disabled={reviewPage === 1}
                  onClick={() => setReviewPage((v) => v - 1)}
                >
                  Назад
                </button>
                <span>{reviewPage}</span>
                <button
                  disabled={reviewPage * 30 >= reviewTotal}
                  onClick={() => setReviewPage((v) => v + 1)}
                >
                  Далее
                </button>
              </div>
            )}
          </section>
        )}
        {expanded && user && (
          <section>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => setReportTarget({ type: "places", id: place.id })}
            >
              <Flag size={14} />
              Сообщить об ошибке
            </Button>
          </section>
        )}
        {message && (
          <p role="status" className="notice">
            {message}
          </p>
        )}
        <small className="muted">
          Обновлено {new Date(place.updated_at).toLocaleDateString("ru-RU")}
        </small>
      </div>
      {reportTarget && (
        <ReportDialog
          target={reportTarget}
          onClose={() => setReportTarget(null)}
          onSent={() => {
            setReportTarget(null);
            setMessage("Сообщение отправлено");
          }}
        />
      )}
      {deleteReview !== null && (
        <DeleteReview
          id={deleteReview}
          onClose={() => setDeleteReview(null)}
          onDeleted={() => {
            setReviews((items) =>
              items.filter((item) => item.id !== deleteReview),
            );
            setReviewTotal((n) => Math.max(0, n - 1));
            setDeleteReview(null);
          }}
        />
      )}
    </aside>
  );
  return expanded
    ? createPortal(
        <dialog
          ref={dialog}
          className="place-fullscreen"
          aria-label={place.name}
          onCancel={(event) => {
            event.preventDefault();
            if (fullscreen) onClose();
            else setExpanded(false);
          }}
        >
          {content}
        </dialog>,
        document.body,
      )
    : content;
}
