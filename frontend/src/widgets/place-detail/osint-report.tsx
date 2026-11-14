"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  FileSearch,
  ExternalLink,
  Loader2,
  RefreshCw,
  Shield,
  Building2,
  Images,
  X,
} from "lucide-react";
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
  assessment?: OsintAssessment;
};

const SECURITY_LEVELS = [
  { id: "low", label: "Низкая" },
  { id: "medium", label: "Средняя" },
  { id: "high", label: "Высокая" },
] as const;

const CONDITION_LEVELS = [
  { id: "abandoned", label: "Заброшен" },
  { id: "active", label: "Действует" },
  { id: "demolished", label: "Снесён" },
] as const;

type TabId = "sources" | "photos";

export function OsintReportTrigger({ placeId }: { placeId: number }) {
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
          <OsintReportDialog placeId={placeId} onClose={() => setOpen(false)} />,
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
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [report, setReport] = useState<OsintReport | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [tab, setTab] = useState<TabId>("sources");

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
    setBusy(true);
    setError("");
    setReport(null);
    setTab("sources");
    api<OsintReport>(`/places/${placeId}/osint-report`, {
      signal: abort.signal,
    })
      .then((data) => {
        if (!abort.signal.aborted) setReport(data);
      })
      .catch((err) => {
        if (!abort.signal.aborted) setError((err as Error).message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setBusy(false);
      });
    return () => abort.abort();
  }, [placeId, reload]);

  const photos = report?.photos ?? [];

  return (
    <dialog
      ref={dialog}
      className="osint-dialog"
      aria-labelledby="osint-title"
      onCancel={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === dialog.current) onClose();
      }}
    >
      <div
        className="osint-dialog-panel"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="osint-dialog-heading">
          <div>
            <h2 id="osint-title">Подробный отчёт</h2>
            <p className="muted">
              Сводка из открытых источников через SearXNG
            </p>
          </div>
          <button type="button" aria-label="Закрыть отчёт" onClick={onClose}>
            <X size={18} />
          </button>
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
              onClick={() => setReload((n) => n + 1)}
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
                  title="Охраняемость"
                  icon={<Shield size={14} aria-hidden="true" />}
                  levels={SECURITY_LEVELS}
                  current={report.assessment.security}
                />
                <LevelMeter
                  title="Состояние"
                  icon={<Building2 size={14} aria-hidden="true" />}
                  levels={CONDITION_LEVELS}
                  current={report.assessment.condition}
                />
                <p className="osint-assessment-note muted">
                  {report.assessment.disclaimer}
                </p>
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
                Фото
                <span>{report.photos_total ?? photos.length}</span>
              </button>
            </div>
            <div className="osint-report-toolbar">
              <small className="muted">
                {tab === "sources"
                  ? report.queries.length > 0
                    ? `Запросы: ${report.queries.join(" · ")}`
                    : "Источники"
                  : (report.image_queries?.length ?? 0) > 0
                    ? `Запросы: ${report.image_queries!.join(" · ")}`
                    : "Фото из открытых источников"}
              </small>
              <button
                type="button"
                className="osint-retry"
                onClick={() => setReload((n) => n + 1)}
              >
                <RefreshCw size={14} aria-hidden="true" />
                Обновить
              </button>
            </div>
            {tab === "sources" ? (
              report.items.length === 0 ? (
                <p className="muted">По открытым источникам ничего не найдено.</p>
              ) : (
                <ul className="osint-result-list">
                  {report.items.map((item) => (
                    <li key={item.url}>
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {item.title}
                        <ExternalLink size={12} aria-hidden="true" />
                      </a>
                      {item.snippet && <p>{item.snippet}</p>}
                      <small className="muted">
                        {[item.engine, item.category].filter(Boolean).join(" · ")}
                      </small>
                    </li>
                  ))}
                </ul>
              )
            ) : photos.length === 0 ? (
              <p className="muted">Фотографии в открытых источниках не найдены.</p>
            ) : (
              <ul className="osint-photo-grid">
                {photos.map((photo) => (
                  <li key={`${photo.image_url}-${photo.source_url}`}>
                    <div className="osint-photo-card">
                      <div className="osint-photo-frame">
                        {/* External OSINT URLs; next/image remote allowlist is not practical here. */}
                        <img
                          src={photo.thumbnail_url || photo.image_url}
                          alt={photo.title}
                          loading="lazy"
                          referrerPolicy="no-referrer"
                          onError={(event) => {
                            const target = event.currentTarget;
                            if (
                              photo.image_url &&
                              target.src !== photo.image_url
                            ) {
                              target.src = photo.image_url;
                            }
                          }}
                        />
                      </div>
                      <div className="osint-photo-meta">
                        <p title={photo.title}>{photo.title}</p>
                        {photo.engine && (
                          <small className="muted">{photo.engine}</small>
                        )}
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
                ))}
              </ul>
            )}
          </div>
        ) : null}
      </div>
    </dialog>
  );
}
