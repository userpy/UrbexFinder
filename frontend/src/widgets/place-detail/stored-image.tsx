"use client";
import { useEffect, useState } from "react";

export function StoredImage({ src, alt }: { src: string; alt: string }) {
  return <StoredImageRequest key={src} src={src} alt={alt} />;
}

function StoredImageRequest({ src, alt }: { src: string; alt: string }) {
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
    </span>}
    {allowed && (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={`${src}?attempt=${attempt}`} alt={alt} loading="lazy"
        style={{ visibility: state === "ready" ? "visible" : "hidden" }}
        onLoad={() => setState("ready")} onError={() => setState("retry")} />
    )}
  </>;
}
