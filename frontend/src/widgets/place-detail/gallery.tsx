"use client";
import { useRef, useState } from "react";
import {
  Camera,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Trash2,
} from "lucide-react";
import { DeletePhoto } from "./delete-photo";
import { Button } from "@/shared/ui/button";
import { Photo } from "@/entities/place";
import { StoredImage } from "./stored-image";
import { PlacePhoto } from "./telegram-photo";

export type SourcePhoto = {
  image_url: string;
  source_url: string;
  title: string;
};

export function sourcePhotoLabel(photo: SourcePhoto): string {
  try {
    const host = new URL(photo.source_url).hostname.replace(/^www\./, "");
    if (host === "podmoskovnye.ru") return "Подмосковные";
    if (["yandex.ru", "yandex.com", "yandex.by", "yandex.kz", "yandex.uz"].includes(host)) return "Яндекс Карты";
  } catch { /* Older records may have incomplete URLs. */ }
  return "Geocaching";
}

export function SourceImage({ photo, alt }: { photo: SourcePhoto; alt: string }) {
  return <StoredImage src={photo.image_url} alt={alt} />;
}

export function PhotoGallery({
  photos: communityPhotos,
  sourcePhotos = [],
  sourceStatus = "",
  name,
  canDelete = () => false,
  upload,
  onDeleted,
}: {
  photos: Photo[];
  sourcePhotos?: SourcePhoto[];
  sourceStatus?: string;
  name: string;
  canDelete?: (photo: Photo) => boolean;
  upload?: React.ReactNode;
  onDeleted: (id: number) => void;
}) {
  const photos = [
    ...communityPhotos,
    ...sourcePhotos.map((photo) => ({ ...photo, id: photo.image_url })),
  ];
  const [deleting, setDeleting] = useState<number | null>(null);
  const [selected, setSelected] = useState(0);
  const touch = useRef<number | null>(null);
  const index = Math.min(selected, Math.max(0, photos.length - 1));
  const photo = photos[index];
  function move(direction: number) {
    setSelected((index + direction + photos.length) % photos.length);
  }
  return (
    <section
      className="place-gallery"
      aria-label="Фотографии места"
      onKeyDown={(event) => {
        if (!photo || event.target instanceof HTMLInputElement) return;
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault();
          move(event.key === "ArrowLeft" ? -1 : 1);
        }
      }}
    >
      <div className="gallery-heading">
        <span>
          <Camera size={16} /> Фотографии
        </span>
        {upload}
        <span className="gallery-total">
          {photos.length ? `${photos.length} фото` : sourceStatus || "Пока нет фото"}
        </span>
      </div>
      <div
        className="gallery-stage"
        tabIndex={0}
        aria-label="Просмотр фото. Переключение стрелками"
        onTouchStart={(event) => {
          touch.current = event.touches[0].clientX;
        }}
        onTouchEnd={(event) => {
          if (photo && touch.current !== null) {
            const distance = event.changedTouches[0].clientX - touch.current;
            if (Math.abs(distance) > 50) move(distance < 0 ? 1 : -1);
          }
          touch.current = null;
        }}
      >
        {photo && "image_url" in photo ? (
          <SourceImage key={photo.id} photo={photo} alt={`${name} — фото ${index + 1}`} />
        ) : photo ? (
          <PlacePhoto
            key={photo.id}
            id={photo.id}
            alt={`${name} — фото ${index + 1}`}
          />
        ) : (
          <div className="gallery-empty">
            <Camera size={40} />
            <p role="status">{sourceStatus || "Фотографии пока не добавлены"}</p>
          </div>
        )}
        {photos.length > 1 && (
          <>
            <button
              className="gallery-arrow gallery-prev"
              aria-label="Предыдущее фото"
              onClick={() => move(-1)}
            >
              <ChevronLeft size={24} />
            </button>
            <button
              className="gallery-arrow gallery-next"
              aria-label="Следующее фото"
              onClick={() => move(1)}
            >
              <ChevronRight size={24} />
            </button>
          </>
        )}
        {photo && (
          <span className="gallery-count" aria-live="polite">
            {index + 1} / {photos.length}
          </span>
        )}
      </div>
      {photo && (
        <div className="gallery-caption">
          <span>
            {"image_url" in photo ? `Фото · ${sourcePhotoLabel(photo)}` : photo.status === "pending"
              ? "На проверке"
              : photo.id < 0
                ? "Фото из Telegram"
                : "Фото сообщества"}
          </span>
          {!("image_url" in photo) && canDelete(photo) && (
            <Button variant="ghost" onClick={() => setDeleting(photo.id)}>
              <Trash2 size={14} /> Удалить фото
            </Button>
          )}
          <a
            href={"image_url" in photo ? photo.image_url : `/api/photos/${photo.id}/content`}
            target="_blank"
            rel="noreferrer"
          >
            Открыть фото <ExternalLink size={13} />
          </a>
          {"image_url" in photo && (
            <a href={photo.source_url} target="_blank" rel="noreferrer">
              {sourcePhotoLabel(photo)} · источник <ExternalLink size={13} />
            </a>
          )}
        </div>
      )}
      {photos.length > 1 && (
        <div className="gallery-thumbnails" aria-label="Выбор фотографии">
          {photos.map((item, i) => (
            <button
              key={item.id}
              className={i === index ? "selected" : ""}
              aria-label={`Фото ${i + 1}`}
              aria-pressed={i === index}
              onClick={() => setSelected(i)}
            >
              {"image_url" in item ? (
                <SourceImage photo={item} alt="" />
              ) : (
                <PlacePhoto key={item.id} id={item.id} alt="" compact />
              )}
              <span>{String(i + 1).padStart(2, "0")}</span>
            </button>
          ))}
        </div>
      )}
      {deleting !== null && (
        <DeletePhoto
          id={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            onDeleted(deleting);
            setDeleting(null);
          }}
        />
      )}
    </section>
  );
}
