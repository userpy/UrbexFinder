"use client";
import { useRef, useState } from "react";
import { Camera, ChevronLeft, ChevronRight, ExternalLink, Trash2 } from "lucide-react";
import { DeletePhoto } from "./delete-photo";
import { Button } from "@/shared/ui/button";
import { Photo } from "@/entities/place";
import { PlacePhoto } from "./telegram-photo";

export function PhotoGallery({
  photos,
  name,
  canDelete = false,
  onDeleted,
}: {
  photos: Photo[];
  name: string;
  canDelete?: boolean;
  onDeleted: (id: number) => void;
}) {
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
        <span>{photos.length ? `${photos.length} фото` : "Пока нет фото"}</span>
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
        {photo ? (
          <PlacePhoto
            key={photo.id}
            id={photo.id}
            alt={`${name} — фото ${index + 1}`}
          />
        ) : (
          <div className="gallery-empty">
            <Camera size={40} />
            <p>Фотографии пока не добавлены</p>
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
          <span>{photo.id < 0 ? "Фото из Telegram" : "Фото сообщества"}</span>
          {canDelete && (
            <Button variant="ghost" onClick={() => setDeleting(photo.id)}>
              <Trash2 size={14} /> Удалить фото
            </Button>
          )}
          <a
            href={`/api/photos/${photo.id}/content`}
            target="_blank"
            rel="noreferrer"
          >
            Открыть фото <ExternalLink size={13} />
          </a>
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
              <PlacePhoto key={item.id} id={item.id} alt="" compact />
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
