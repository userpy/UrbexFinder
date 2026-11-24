"use client";
import { useEffect, useState } from "react";

type StoredImageProps = { src: string; previewSrc?: string; alt: string; sourceName?: string };

export function StoredImage(props: StoredImageProps) {
  return <StoredImageRequest key={`${props.src}|${props.previewSrc || ""}`} {...props} />;
}

function useImageRequest(src?: string) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<"loading" | "ready" | "retry">("loading");
  const allowed = !!src && /^\/api\/source-images\/[a-f0-9]{64}$/.test(src);
  useEffect(() => {
    if (state !== "retry" || attempt >= 30 || !allowed) return;
    const timer = setTimeout(() => {
      setState("loading");
      setAttempt((value) => value + 1);
    }, 3000);
    return () => clearTimeout(timer);
  }, [state, attempt, allowed]);
  return { allowed, attempt, state, url: `${src}?attempt=${attempt}`,
    onLoad: () => setState("ready"), onError: () => setState("retry") };
}

function StoredImageRequest({ src, previewSrc, alt, sourceName }: StoredImageProps) {
  const main = useImageRequest(src);
  const preview = useImageRequest(previewSrc !== src && main.state !== "ready" ? previewSrc : undefined);
  const previewVisible = preview.allowed && preview.state === "ready" && main.state !== "ready";
  const loading = (main.allowed && main.attempt < 30) || (preview.allowed && preview.attempt < 30);
  return <>
    {main.state !== "ready" && !previewVisible && <span role="status" className="stored-image-status">
      {loading ? "Загрузка фотографии…" : "Фото временно недоступно"}
      {sourceName && <span>Источник: {sourceName}</span>}
    </span>}
    {main.allowed && (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={main.url} alt={alt} loading="lazy" aria-hidden={main.state !== "ready"}
        style={{ visibility: main.state === "ready" ? "visible" : "hidden",
          position: main.state === "ready" ? undefined : "absolute" }}
        onLoad={main.onLoad} onError={main.onError} />
    )}
    {preview.allowed && (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={preview.url} alt={alt} loading="lazy" aria-hidden={!previewVisible}
        style={{ position: "absolute", inset: 0, visibility: previewVisible ? "visible" : "hidden" }}
        onLoad={preview.onLoad} onError={preview.onError} />
    )}
    {previewVisible && <span className="stored-image-preview-label">Миниатюра</span>}
  </>;
}
