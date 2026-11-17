"use client";
import { useEffect, useState } from "react";

type StoredImageProps = { src: string; alt: string; sourceName?: string };

export function StoredImage({ src, alt, sourceName }: StoredImageProps) {
  return <StoredImageRequest key={src} src={src} alt={alt} sourceName={sourceName} />;
}

function StoredImageRequest({ src, alt, sourceName }: StoredImageProps) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<"loading" | "ready" | "retry">("loading");
  const allowed = /^\/api\/source-images\/[a-f0-9]{64}$/.test(src);
  useEffect(() => {
    if (state !== "retry" || attempt >= 30 || !allowed) return;
    const timer = setTimeout(() => {
      setState("loading");
      setAttempt((value) => value + 1);
    }, 3000);
    return () => clearTimeout(timer);
  }, [state, attempt, allowed]);
  return <>
    {state !== "ready" && <span role="status" className="stored-image-status">
      {!allowed || attempt >= 30 ? "Фото временно недоступно" : "Загрузка фотографии…"}
      {sourceName && <span>Источник: {sourceName}</span>}
    </span>}
    {allowed && (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={`${src}?attempt=${attempt}`} alt={alt} loading="lazy"
        style={{ visibility: state === "ready" ? "visible" : "hidden" }}
        onLoad={() => setState("ready")} onError={() => setState("retry")} />
    )}
  </>;
}
