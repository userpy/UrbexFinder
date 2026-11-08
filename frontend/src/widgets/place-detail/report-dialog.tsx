"use client";
import { useEffect, useRef, useState } from "react";
import { X, Send } from "lucide-react";
import { api, body } from "@/shared/api";
import { Button } from "@/shared/ui/button";
export function ReportDialog({
  target,
  onClose,
  onSent,
}: {
  target: { type: "places" | "reviews"; id: number };
  onClose: () => void;
  onSent: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="report-dialog"
      aria-labelledby="report-title"
      onCancel={(event) => {
        event.preventDefault();
        event.stopPropagation();
        if (!busy) onClose();
      }}
    >
      <div className="report-dialog-heading">
        <h2 id="report-title">
          {target.type === "places"
            ? "Сообщить об ошибке"
            : "Пожаловаться на отзыв"}
        </h2>
        <button
          type="button"
          aria-label="Закрыть сообщение об ошибке"
          disabled={busy}
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </div>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError("");
          try {
            await api("/reports", {
              method: "POST",
              body: body({
                target_type: target.type,
                target_id: target.id,
                text: text.trim(),
              }),
            });
            onSent();
          } catch (error) {
            setError((error as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          Что нужно проверить?
          <textarea
            autoFocus
            required
            minLength={5}
            maxLength={4000}
            rows={5}
            value={text}
            disabled={busy}
            onChange={(event) => setText(event.target.value)}
            placeholder="Опишите ошибку в сведениях о месте"
          />
        </label>
        <small className="muted">Не менее 5 символов</small>
        {error && (
          <p role="alert" className="notice">
            {error}
          </p>
        )}
        <div className="actions">
          <Button type="submit" disabled={busy || text.trim().length < 5}>
            <Send size={15} />
            {busy ? "Отправка…" : "Отправить"}
          </Button>
        </div>
      </form>
    </dialog>
  );
}
