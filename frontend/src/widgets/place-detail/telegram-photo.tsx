"use client";
import Image from "next/image";
import { useEffect, useState } from "react";

export function PlacePhoto({
  id,
  alt,
  compact = false,
}: {
  id: number;
  alt: string;
  compact?: boolean;
}) {
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!failed || attempt >= 2) return;
    const timer = setTimeout(
      () => {
        setFailed(false);
        setAttempt((value) => value + 1);
      },
      1500 * (attempt + 1),
    );
    return () => clearTimeout(timer);
  }, [failed, attempt]);
  if (failed)
    return compact ? (
      <span className="thumbnail-loading">{attempt < 2 ? "…" : "Фото"}</span>
    ) : (
      <div className="photo-load-error" role="status">
        <span>
          {attempt < 2
            ? "Повторная загрузка фото…"
            : "Не удалось загрузить фото"}
        </span>
        {attempt >= 2 && (
          <button
            type="button"
            onClick={(event) => {
              event.preventDefault();
              setAttempt(0);
              setFailed(false);
            }}
          >
            Повторить
          </button>
        )}
      </div>
    );
  return (
    <Image
      key={attempt}
      unoptimized
      width={720}
      height={480}
      src={`/api/photos/${id}/content${attempt ? `?retry=${attempt}` : ""}`}
      alt={alt}
      onError={() => setFailed(true)}
    />
  );
}
