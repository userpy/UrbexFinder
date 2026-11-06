"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/shared/api";
import { Button } from "@/shared/ui/button";
export function DeleteReview({
  id,
  onClose,
  onDeleted,
}: {
  id: number;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [deleted, setDeleted] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="route-confirm"
      aria-labelledby="delete-review-title"
      onCancel={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (!busy) {
          if (deleted) onDeleted();
          else onClose();
        }
      }}
    >
      <h2 id="delete-review-title">
        {deleted ? "Комментарий удалён" : "Удалить комментарий?"}
      </h2>
      <p>Комментарий больше не будет отображаться на сайте и в боте.</p>
      {error && <p role="alert">{error}</p>}
      {deleted ? (
        <div className="actions">
          <Button type="button" autoFocus onClick={onDeleted}>Закрыть</Button>
        </div>
      ) : (
      <div className="actions">
        <Button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await api(`/admin/reviews/${id}`, { method: "DELETE" });
              setDeleted(true);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Да
        </Button>
        <Button autoFocus variant="outline" disabled={busy} onClick={onClose}>
          Нет
        </Button>
      </div>
      )}
    </dialog>
  );
}
