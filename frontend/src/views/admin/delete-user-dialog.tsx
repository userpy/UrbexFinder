"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/shared/api";
import { Button } from "@/shared/ui/button";
export function DeleteUserDialog({
  id,
  name,
  onClose,
  onDeleted,
}: {
  id: number;
  name: string;
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
      aria-labelledby="delete-user-title"
      onCancel={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (!busy) onClose();
      }}
    >
      <h2 id="delete-user-title">Удалить пользователя?</h2>
      <p>{name}</p>
      <p>
        Учётная запись, сеансы и личные маршруты будут удалены. Добавленные
        места и материалы сохранятся без привязки к имени пользователя.
      </p>
      {error && <p role="alert">{error}</p>}
      <div className="actions">
        <Button
          type="button"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await api(`/admin/users/${id}`, { method: "DELETE" });
              onDeleted();
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Да, удалить
        </Button>
        <Button type="button" autoFocus variant="outline" disabled={busy} onClick={onClose}>
          Нет
        </Button>
      </div>
    </dialog>
  );
}
