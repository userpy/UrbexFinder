"use client";
import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { SubmitView } from ".";

export function SubmitModal({ direct = false }: { direct?: boolean }) {
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  function close() {
    if (direct) router.replace("/");
    else router.back();
  }
  useEffect(() => {
    const previous = document.activeElement;
    const overflow = document.body.style.overflow;
    dialog.current?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = overflow;
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="submit-modal"
      aria-label="Добавить место"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
    >
      <SubmitView onClose={close} />
    </dialog>
  );
}
