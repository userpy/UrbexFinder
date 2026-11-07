"use client";
import Link from "next/link";
import { X } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { useState } from "react";
import { useSession } from "@/entities/session";
import { Place } from "@/entities/place";
import { PlaceForm } from "@/widgets/place-form";
export function SubmitView({ onClose }: { onClose?: () => void }) {
  const { user, loading } = useSession(),
    [place, setPlace] = useState<Place | null>(null);
  if (loading) return <main className="page">Загрузка…</main>;
  if (!user)
    return (
      <main className="page">
        {onClose && (
          <Button variant="ghost" onClick={onClose}>
            <X size={18} /> Закрыть
          </Button>
        )}
        <h1>Предложить место</h1>
        <p>
          <Link href="/login">Войдите или зарегистрируйтесь</Link>, чтобы
          отправить заявку.
        </p>
      </main>
    );
  return (
    <main className="page narrow">
      <section className="submit-card" aria-labelledby="submit-title">
        <header className="submit-card-heading">
          <div className="eyebrow">КАРТА СОЗДАЁТСЯ ВМЕСТЕ</div>
          {onClose ? (
            <Button
              variant="ghost"
              onClick={onClose}
              aria-label="Закрыть форму добавления места"
            >
              <X size={18} /> Закрыть
            </Button>
          ) : (
            <Button asChild variant="ghost">
              <Link href="/" aria-label="Закрыть форму добавления места">
                <X size={18} /> Закрыть
              </Link>
            </Button>
          )}
          <h1 id="submit-title">
            {place ? "Заявка отправлена" : "Новое место"}
          </h1>
        </header>
        <div>
          {place ? (
            <>
              <p>«{place.name}» появится на карте после проверки.</p>
              <Link href="/account">Перейти к моим заявкам →</Link>
            </>
          ) : (
            <PlaceForm onSuccess={setPlace} />
          )}
        </div>
      </section>
    </main>
  );
}
