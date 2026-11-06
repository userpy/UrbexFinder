"use client";
import Link from "next/link";
import { X } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { useState } from "react";
import { useSession } from "@/entities/session";
import { Place } from "@/entities/place";
import { PlaceForm } from "@/widgets/place-form";
import { api } from "@/shared/api";
export function SubmitView() {
  const { user, loading } = useSession(),
    [place, setPlace] = useState<Place | null>(null),
    [message, setMessage] = useState("");
  if (loading) return <main className="page">Загрузка…</main>;
  if (!user)
    return (
      <main className="page">
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
          <div>
            <div className="eyebrow">КАРТА СОЗДАЁТСЯ ВМЕСТЕ</div>
            <h1 id="submit-title">{place ? "Заявка отправлена" : "Новое место"}</h1>
          </div>
          <Button asChild variant="ghost">
            <Link href="/" aria-label="Закрыть форму добавления места">
              <X size={18} /> Закрыть
            </Link>
          </Button>
        </header>
      <div>
        {place ? (
          <>
            <p>
              «{place.name}» появится на карте после проверки. Добавьте
              фотографии к заявке.
            </p>
            <label className="upload">
              Загрузить фотографию
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  if (f) {
                    const form = new FormData();
                    form.set("file", f);
                    try {
                      await api(`/places/${place.id}/photos`, {
                        method: "POST",
                        body: form,
                      });
                      setMessage("Фото добавлено в очередь проверки");
                    } catch (e) {
                      setMessage((e as Error).message);
                    }
                  }
                }}
              />
            </label>
            <p role="status">{message}</p>
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
