"use client";
import { DeleteReview } from "./delete-review";
export { DeleteReview } from "./delete-review";
import { ReportDialog } from "./report-dialog";
import { PlaceDescription } from "./description";
import { PlaceRating } from "./rating";
import { PhotoGallery } from "./gallery";
import { PlacePhoto } from "./telegram-photo";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import {
  X,
  Bookmark,
  Camera,
  ImagePlus,
  MapPin,
  Flag,
  Maximize2,
  Copy,
  ExternalLink,
  Mail,
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
  const staff = !!user && ["admin", "moderator"].includes(user.role);
  const canUpload = !!user;
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const photoInput = useRef<HTMLInputElement>(null);
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
  const [routeNotice, setRouteNotice] = useState("");
  useEffect(() => {
    if (message !== "Сообщение отправлено") return;
    const timer = setTimeout(() => setMessage(""), 3000);
    return () => clearTimeout(timer);
  }, [message, reportTarget]);
  useEffect(() => {
    if (!routeNotice) return;
    const timer = setTimeout(() => setRouteNotice(""), 3000);
    return () => clearTimeout(timer);
  }, [routeNotice]);
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
        {expanded ? (
          <button
            className="detail-expand"
            onClick={() => {
              if (fullscreen) onClose();
              else setExpanded(false);
            }}
          >
            <X size={19} />
            Закрыть
          </button>
        ) : (
          <>
            <button
              ref={expandButton}
              className="detail-expand"
              onClick={() => setExpanded(true)}
            >
              <Maximize2 size={17} />
              Во весь экран
            </button>
            <button className="detail-close" aria-label="Закрыть карточку" onClick={onClose}>
              <X size={19} />
            </button>
          </>
        )}
      </div>
      {expanded ? (
        <PhotoGallery
          key={place.id}
          photos={photos}
          name={place.name}
          canDelete={(photo) =>
            staff ||
            (!!user && photo.author_id === user.id)
          }
          upload={
            canUpload && (
              <div className="gallery-upload">
                <input
                  ref={photoInput}
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  hidden
                  aria-label="Фотография для карточки"
                  disabled={uploading}
                  onChange={async (event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (!file) return;
                    setUploading(true);
                    setUploadError("");
                    const form = new FormData();
                    form.set("file", file);
                    try {
                      const photo = await api<Photo>(
                        `/places/${place.id}/photos`,
                        { method: "POST", body: form },
                      );
                      setPhotos((items) => [photo, ...items]);
                    } catch (error) {
                      setUploadError((error as Error).message);
                    } finally {
                      setUploading(false);
                    }
                  }}
                />
                <Button
                  variant="ghost"
                  disabled={uploading}
                  onClick={() => photoInput.current?.click()}
                >
                  <ImagePlus size={14} aria-hidden="true" />
                  {uploading ? "Загрузка…" : "Добавить фото"}
                </Button>
                {uploadError && (
                  <p className="notice" role="alert">
                    {uploadError}
                  </p>
                )}
              </div>
            )
          }
          onDeleted={(id) =>
            setPhotos((items) => items.filter((photo) => photo.id !== id))
          }
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
            {place.condition !== "unknown" && conditions[place.condition] && (
              <span className="photo-badge">{conditions[place.condition]}</span>
            )}
          </div>
          {photos[0]?.id < 0 && (
            <small className="telegram-photo-source">Фото из Telegram</small>
          )}
        </>
      )}
      <div className="detail-body">
        <PlaceRating ratingAverage={place.rating_avg} ratingCount={place.rating_count} />
        <h2>{place.name}</h2>
        {place.category && (
          <p className="muted location place-category">
            <CategoryIcon
              category={place.category}
              icon={place.category_icon}
              width={18}
              height={18}
            />
            {place.category}
          </p>
        )}
        <p className="muted location">
          <MapPin size={14} />
          {place.full_address || place.region}
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
              setRouteNotice("");
              try {
                if (added) {
                  await api(`/places/${place.id}/itinerary`, {
                    method: "DELETE",
                  });
                  setMembership({ id: place.id, added: false });
                  setRouteNotice("Место удалено из маршрутного листа");
                  return;
                }
                const result = await api<{
                  name: string;
                  already_added: boolean;
                }>(`/places/${place.id}/itinerary`, { method: "POST" });
                setMembership({ id: place.id, added: true });
                setRouteNotice(
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
          <PlaceDescription description={place.description} />
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
        {routeNotice && (
          <p role="status" className="notice">
            {routeNotice}
          </p>
        )}
        {message && (
          <p
            role="status"
            className={message === "Сообщение отправлено" ? "success-toast" : "notice"}
          >
            {message === "Сообщение отправлено" && <Mail size={22} aria-hidden="true" />}
            {message}
          </p>
        )}
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
