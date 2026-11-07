"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/shared/api";
import { Button } from "@/shared/ui/button";
export function DeletePhoto({
  id,
  onClose,
  onDeleted,
}: {
  id: number;
  onClose: () => void;
  onDeleted: () => void;
}) {
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
      aria-labelledby="delete-photo-title"
      onCancel={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (!busy) onClose();
      }}
    >
      <h2 id="delete-photo-title">Удалить фотографию?</h2>
      <p>Фотография больше не будет отображаться на сайте и в боте.</p>
      {error && <p role="alert">{error}</p>}
      <div className="actions">
        <Button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await api(`/photos/${id}`, { method: "DELETE" });
              onDeleted();
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
    </dialog>
  );
}
