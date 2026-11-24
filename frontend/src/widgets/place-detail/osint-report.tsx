"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  FileSearch,
  ExternalLink,
  Loader2,
  RefreshCw,
  Building2,
  Images,
  Image as ImageIcon,
  Video,
  Globe,
  Youtube,
  X,
} from "lucide-react";
import { StoredImage } from "./stored-image";
import { api } from "@/shared/api";

export type OsintItem = {
  title: string;
  url: string;
  snippet: string;
  engine?: string | null;
  category?: string | null;
  score?: number | null;
  query: string;
};

export type OsintPhoto = {
  title: string;
  image_url: string;
  thumbnail_url: string;
  source_url: string;
  engine?: string | null;
  score?: number | null;
  query: string;
};

export type OsintSignal = {
  term: string;
  url: string;
  title: string;
  in_title: boolean;
};

export type OsintAxis = {
  level: string;
  label: string;
  confidence: "low" | "medium" | "high";
  signals: OsintSignal[];
};

export type OsintAssessment = {
  security: OsintAxis;
  condition: OsintAxis;
  summary: string;
  disclaimer: string;
};

type VerificationDecision = {
  status: "accepted" | "unconfirmed" | "rejected";
  reasons: string[];
  candidate: { title?: string; url?: string; source_url?: string; image_url?: string };
};

export type OsintReport = {
  place_id: number;
  place_name: string;
  queries: string[];
  image_queries?: string[];
  source: string;
  total: number;
  items: OsintItem[];
  photos?: OsintPhoto[];
  photos_total?: number;
  verification?: {
    location?: { status: string; reason: string; coordinate_region?: string };
    version: number;
    sources: VerificationDecision[];
    photos: VerificationDecision[];
  };
  assessment?: OsintAssessment;
  cached?: boolean;
  updated_at?: string | null;
};

const CONDITION_LEVELS = [
  { id: "abandoned", label: "Заброшен" },
  { id: "active", label: "Действует" },
  { id: "demolished", label: "Снесён" },
] as const;

type TabId = "sources" | "photos";
type MediaKind = "photo" | "video";
type SourceKind =
  | "vk"
  | "youtube"
  | "rutube"
  | "urban3p"
  | "geocache"
  | "wikimapia"
  | "livejournal"
  | "swalker"
  | "caves"
  | "planetadorog"
  | "podmoskovnye"
  | "urbexstalker"
  | "dzen"
  | "web";

function mediaKindFor(photo: OsintPhoto): MediaKind {
  const blob = [
    photo.title,
    photo.source_url,
    photo.image_url,
    photo.thumbnail_url,
    photo.engine,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  if (
    /youtube\.com|youtu\.be|vk\.(?:com|ru)\/video|rutube\.|vimeo\.|tiktok\.|\/video[-_/]|\bвидео\b|\bvideo\b/.test(
      blob,
    )
  ) {
    return "video";
  }
  return "photo";
}

function sourceKindFor(item: {
  engine?: string | null;
  title?: string | null;
  source_url?: string | null;
  image_url?: string | null;
  url?: string | null;
}): SourceKind {
  const sourceUrl = item.source_url || item.url || item.image_url;
  if (sourceUrl) {
    try {
      const host = new URL(sourceUrl).hostname.toLowerCase();
      if (host === "podmoskovnye.ru" || host.endsWith(".podmoskovnye.ru"))
        return "podmoskovnye";
      if (host === "wikimapia.org" || host.endsWith(".wikimapia.org"))
        return "wikimapia";
    } catch {
      // Older reports can contain incomplete URLs; fall back to source metadata.
    }
  }
  const blob = [
    item.engine,
    item.source_url,
    item.url,
    item.image_url,
    item.title,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  if (/\bvk\b|vk\.com|vk\.ru|userapi\.com/.test(blob)) return "vk";
  if (/youtube|youtu\.be/.test(blob)) return "youtube";
  if (/rutube/.test(blob)) return "rutube";
  if (/urban3p/.test(blob)) return "urban3p";
  if (/wikimapia/.test(blob)) return "wikimapia";
  if (
    /geocach|геокеш|геокэш|opencaching|geocaching\.(?:com|ru)|geocaching\.su/.test(
      blob,
    )
  ) {
    return "geocache";
  }
  if (/livejournal|\blive.?journal\b|\.lj\.(?:com|ru)\b/.test(blob)) {
    return "livejournal";
  }
  if (/swalker/.test(blob)) return "swalker";
  if (/caves\.ru/.test(blob)) return "caves";
  if (/planetadorog|планета.?дорог/.test(blob)) return "planetadorog";
  if (/urbexstalker/.test(blob)) return "urbexstalker";
  if (/\bdzen\b|dzen\.ru|zen\.yandex|dzeninfra/.test(blob)) return "dzen";
  return "web";
}

function VkGlyph({ size = 12 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="currentColor"
    >
      <path d="M12.5 8.2h1.7c.1 1.7.8 2.7 1.7 3.2V8.2h1.6v5.8h-1.6v-.2c-1.1-.5-1.9-1.7-2-3.3h-.1c-.3 1.7-1.3 3.1-2.7 3.5v2.1H9.4v-2.1c-1.4-.4-2.5-1.8-2.8-3.5H6.5c.2 2.1 1.3 3.6 2.6 4.2-.9.5-2.1 1.5-2.7 3.4H4.7c.7-2.1 2.2-3.3 3.3-3.7-1.1-.6-2.2-1.9-2.4-3.9h1.7c.2 1.6.9 2.7 1.8 3.1V8.2h1.6v3.2c.9-.5 1.6-1.5 1.8-3.2z" />
    </svg>
  );
}

function Urban3pGlyph({ size = 12 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 20V9l8-5 8 5v11" />
      <path d="M9 20v-7h6v7" />
    </svg>
  );
}

function GeocacheGlyph({ size = 12 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="9" />
      <path d="m16 8-2.5 5.5L8 16l2.5-5.5Z" />
    </svg>
  );
}

function LiveJournalGlyph({ size = 12 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M5 4h11a2 2 0 0 1 2 2v14l-3-2-3 2-3-2-3 2V6a2 2 0 0 1 2-2z" />
      <path d="M9 9h6M9 13h4" />
    </svg>
  );
}

function SwalkerGlyph({ size = 12 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3" />
      <path d="M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" />
    </svg>
  );
}

function CavesGlyph({ size = 12 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 20 8 8l4 6 3-4 6 10H3z" />
      <path d="M9 20c1.5-3 3-4.5 5-4.5S17 17 18.5 20" />
    </svg>
  );
}

function PlanetadorogGlyph({ size = 12 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
    </svg>
  );
}

function UrbexStalkerGlyph({ size = 12 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 20V7l8-4 8 4v13" />
      <path d="M9 20v-6h6v6" />
      <circle cx="12" cy="10" r="1.5" />
    </svg>
  );
}

function DzenGlyph({ size = 12 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12h8M12 8v8" />
    </svg>
  );
}

function WikimapiaGlyph({ size = 12 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5" />
      <path d="m6 8 3 9 3-6 3 6 3-9" stroke="#ef4444" />
    </svg>
  );
}

function PodmoskovnyeGlyph({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
      {/* Simplified lady in a hat from the estate site's wordmark. */}
      <path d="M8 3.7c.7-1.2 2.3-1.8 4-1.3l1.5 1.2 3 .5-.4 1.1-8.8-.5-.8-.7ZM10 5.4h3l-.1 2-1.1 1.3-1.5-.8-.7-1.3Z" />
      <path d="m10.4 8.5 2.3.2 1.1 3.8 2.1 1-.5 1.1-2.7-1.2-.1 3.4c.3 2.3 1.4 3.9 3.5 4.7H5.8c2.2-2.1 2.9-4.9 3.2-8.3l-.8-1.5.7-2.3Z" />
      <path d="m15.3 13.9 1.6 7.5" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M3 22h18" fill="none" stroke="#84b879" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

function SourceGlyph({ kind }: { kind: SourceKind }) {
  if (kind === "podmoskovnye") return <PodmoskovnyeGlyph />;
  if (kind === "vk") return <VkGlyph size={12} />;
  if (kind === "youtube") return <Youtube size={12} aria-hidden="true" />;
  if (kind === "rutube") return <Video size={12} aria-hidden="true" />;
  if (kind === "urban3p") return <Urban3pGlyph size={12} />;
  if (kind === "geocache") return <GeocacheGlyph size={12} />;
  if (kind === "wikimapia") return <WikimapiaGlyph size={12} />;
  if (kind === "livejournal") return <LiveJournalGlyph size={12} />;
  if (kind === "swalker") return <SwalkerGlyph size={12} />;
  if (kind === "caves") return <CavesGlyph size={12} />;
  if (kind === "planetadorog") return <PlanetadorogGlyph size={12} />;
  if (kind === "urbexstalker") return <UrbexStalkerGlyph size={12} />;
  if (kind === "dzen") return <DzenGlyph size={12} />;
  return <Globe size={12} aria-hidden="true" />;
}

const SOURCE_LABELS: Record<SourceKind, string> = {
  vk: "VK",
  youtube: "YouTube",
  rutube: "Rutube",
  urban3p: "Urban3P",
  geocache: "Geocaching",
  wikimapia: "Wikimapia",
  livejournal: "LJ",
  swalker: "Swalker",
  caves: "Caves",
  planetadorog: "Планета",
  podmoskovnye: "Подмосковные",
  urbexstalker: "Stalker",
  dzen: "Дзен",
  web: "Web",
};

export function OsintReportTrigger({ placeId, onUpdated }: { placeId: number; onUpdated?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="osint-trigger"
        aria-label="Подробный отчёт"
        title="Подробный отчёт"
        onClick={() => setOpen(true)}
      >
        <FileSearch size={14} aria-hidden="true" />
        Отчёт
      </button>
      {open &&
        createPortal(
          <OsintReportDialog key={placeId} placeId={placeId} onClose={(updated) => {
            setOpen(false);
            if (updated) onUpdated?.();
          }} />,
          document.body,
        )}
    </>
  );
}

function LevelMeter({
  title,
  icon,
  levels,
  current,
  unknownLabel = "Неясно",
}: {
  title: string;
  icon: ReactNode;
  levels: readonly { id: string; label: string }[];
  current: OsintAxis;
  unknownLabel?: string;
}) {
  const activeId = levels.some((level) => level.id === current.level)
    ? current.level
    : "unknown";
  return (
    <div className={`osint-meter osint-meter-${activeId}`} role="group" aria-label={title}>
      <div className="osint-meter-head">
        <span>
          {icon}
          {title}
        </span>
        <strong>{activeId === "unknown" ? unknownLabel : current.label}</strong>
      </div>
      <div className="osint-meter-levels" aria-hidden={activeId === "unknown"}>
        {levels.map((level) => (
          <span
            key={level.id}
            className={
              level.id === activeId
                ? "osint-meter-level is-active"
                : "osint-meter-level"
            }
          >
            {level.label}
          </span>
        ))}
      </div>
    </div>
  );
}

function OsintReportDialog({
  placeId,
  onClose,
}: {
  placeId: number;
  onClose: (updated: boolean) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const reportUpdated = useRef(false);
  function close() {
    onClose(reportUpdated.current);
  }
  const [report, setReport] = useState<OsintReport | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [tab, setTab] = useState<TabId>("sources");
  const [failedPhotos, setFailedPhotos] = useState<Set<string>>(new Set());
  function refreshReport() {
    setBusy(true);
    setError("");
    setReport(null);
    setFailedPhotos(new Set());
    setTab("sources");
    setReload((n) => n + 1);
  }

  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (!node.open) node.showModal();
    return () => {
      if (node.open) node.close();
    };
  }, []);

  useEffect(() => {
    const abort = new AbortController();
    const path =
      reload > 0
        ? `/places/${placeId}/osint-report?refresh=1`
        : `/places/${placeId}/osint-report`;
    api<OsintReport>(path, {
      signal: abort.signal,
    })
      .then((data) => {
        if (!abort.signal.aborted) {
          if (data.cached === false || reload > 0) reportUpdated.current = true;
          setReport(data);
        }
      })
      .catch((err) => {
        if (!abort.signal.aborted) setError((err as Error).message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setBusy(false);
      });
    return () => abort.abort();
  }, [placeId, reload]);

  const photos = (report?.photos ?? []).filter(
    (photo) => !failedPhotos.has(photo.image_url),
  );
  const unavailableSources = Array.from(new Set(
    (report?.photos ?? [])
      .filter((photo) => failedPhotos.has(photo.image_url))
      .map((photo) => photo.source_url),
  ));

  const verificationRows = report?.verification?.[tab === "sources" ? "sources" : "photos"] ?? [];
  const withheld = verificationRows.filter((row) => row.status !== "accepted");

  return (
    <dialog
      ref={dialog}
      className="osint-dialog"
      aria-labelledby="osint-title"
      onCancel={(event) => {
        event.preventDefault();
        event.stopPropagation();
        close();
      }}
      onClick={(event) => {
        if (event.target === dialog.current) close();
      }}
    >
      <div
        className="osint-dialog-panel"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="osint-dialog-heading">
          <div>
            <h2 id="osint-title">Подробный отчёт</h2>
            {report?.updated_at && !busy && !error && (
              <p className="muted">
                {report.cached ? "Сохранён" : "Обновлён"}{" "}
                {new Date(report.updated_at).toLocaleString("ru-RU")}
              </p>
            )}
          </div>
          <div className="osint-dialog-actions">
            {!busy && (
              <button
                type="button"
                className="osint-retry"
                aria-label="Обновить отчёт"
                title="Обновить отчёт"
                onClick={refreshReport}
              >
                <RefreshCw size={14} aria-hidden="true" />
              </button>
            )}
            <button type="button" aria-label="Закрыть отчёт" onClick={close}>
              <X size={18} />
            </button>
          </div>
        </div>
        {busy ? (
          <div className="osint-dialog-loading" role="status" aria-live="polite">
            <Loader2 size={28} className="osint-spin" aria-hidden="true" />
            <p>Ищем сведения в открытых источниках…</p>
          </div>
        ) : error ? (
          <div className="osint-dialog-error">
            <p role="alert" className="notice">
              {error}
            </p>
            <button
              type="button"
              className="osint-retry"
              onClick={refreshReport}
            >
              <RefreshCw size={14} aria-hidden="true" />
              Повторить
            </button>
          </div>
        ) : report ? (
          <div className="osint-report-body">
            {report.assessment && (
              <section className="osint-indicators" aria-label="Индикаторы оценки">
                <LevelMeter
                  title="Состояние"
                  icon={<Building2 size={14} aria-hidden="true" />}
                  levels={CONDITION_LEVELS}
                  current={report.assessment.condition}
                />
              </section>
            )}
            <div className="osint-tabs" role="tablist" aria-label="Разделы отчёта">
              <button
                type="button"
                role="tab"
                aria-selected={tab === "sources"}
                className={tab === "sources" ? "is-active" : undefined}
                onClick={() => setTab("sources")}
              >
                <FileSearch size={14} aria-hidden="true" />
                Источники
                <span>{report.total}</span>
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === "photos"}
                className={tab === "photos" ? "is-active" : undefined}
                onClick={() => setTab("photos")}
              >
                <Images size={14} aria-hidden="true" />
                Фото и Видео
                <span>{photos.length}</span>
              </button>
            </div>
            {report.verification?.location && (
              <p className="osint-verification-reason" role="status">
                {report.verification.location.reason}
                {report.verification.location.coordinate_region && ` (${report.verification.location.coordinate_region})`}
              </p>
            )}
            {withheld.length > 0 && (
              <details className="osint-verification">
                <summary>Не включены в отчёт: {withheld.length}</summary>
                <p className="muted">Эти материалы не подтверждают сведения об объекте и не участвуют в оценке состояния и охраны.</p>
                <ul className="osint-result-list">
                  {withheld.map((row, index) => (
                    <li key={`${row.candidate.url || row.candidate.image_url}-${index}`}>
                      <span>{row.status === "rejected" ? "Отклонён" : "Не подтверждён"}: </span>
                      <a href={row.candidate.url || row.candidate.source_url} target="_blank" rel="noopener noreferrer">
                        {row.candidate.title || "Источник"}
                      </a>
                      <p>{row.reasons.join(". ")}</p>
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {tab === "photos" && unavailableSources.length > 0 && (
              <div role="status" className="muted">
                <p>Не удалось загрузить часть фотографий из внешних источников.</p>
                <ul>
                  {unavailableSources.map((url) => (
                    <li key={url}>
                      <a href={url} target="_blank" rel="noopener noreferrer">
                        Открыть источник: {url}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {tab === "sources" ? (
              report.items.length === 0 ? (
                <p className="muted">Подтверждённые источники об этом объекте не найдены.</p>
              ) : (
                <ul className="osint-result-list">
                  {report.items.map((item) => {
                    const source = sourceKindFor(item);
                    return (
                      <li key={item.url}>
                        <div className="osint-result-head">
                          <span
                            className={`osint-source-badge is-${source}`}
                            title={SOURCE_LABELS[source]}
                          >
                            <SourceGlyph kind={source} />
                            <span className={source === "wikimapia" ? "sr-only" : undefined}>
                              {SOURCE_LABELS[source]}
                            </span>
                          </span>
                          <a
                            href={item.url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {item.title}
                            <ExternalLink size={12} aria-hidden="true" />
                          </a>
                        </div>
                        {item.snippet && <p>{item.snippet}</p>}
                        {report.verification?.sources.find((row) => row.status === "accepted" && row.candidate.url === item.url)?.reasons.map((reason) => (
                          <p key={reason} className="osint-verification-reason">{reason}</p>
                        ))}
                      </li>
                    );
                  })}
                </ul>
              )
            ) : photos.length === 0 ? (
              <p className="muted">{failedPhotos.size > 0
                ? "Нет доступных для показа фотографий. Попробуйте обновить отчёт позже."
                : "Фотографии с подтверждённой привязкой к объекту не найдены."}</p>
            ) : (
              <ul className="osint-photo-grid">
                {photos.map((photo) => {
                  const media = mediaKindFor(photo);
                  const source = sourceKindFor(photo);
                  return (
                    <li key={`${photo.image_url}-${photo.source_url}`}>
                      <div className="osint-photo-card">
                        <div className="osint-photo-frame">
                          <StoredImage src={photo.image_url} alt={photo.title} />
                          <div className="osint-photo-badges" aria-hidden="true">
                            <span
                              className={
                                media === "video"
                                  ? "osint-media-badge is-video"
                                  : "osint-media-badge is-photo"
                              }
                              title={media === "video" ? "Видео" : "Фото"}
                            >
                              {media === "video" ? (
                                <Video size={12} />
                              ) : (
                                <ImageIcon size={12} />
                              )}
                            </span>
                            <span
                              className={`osint-source-badge is-${source}`}
                              title={SOURCE_LABELS[source]}
                            >
                              <SourceGlyph kind={source} />
                              <span className={source === "wikimapia" ? "sr-only" : undefined}>
                                {SOURCE_LABELS[source]}
                              </span>
                            </span>
                          </div>
                        </div>
                        <div className="osint-photo-meta">
                          <p title={photo.title}>{photo.title}</p>
                          <a
                            className="osint-photo-source"
                            href={photo.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            К источнику
                            <ExternalLink size={12} aria-hidden="true" />
                          </a>
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        ) : null}
      </div>
    </dialog>
  );
}
