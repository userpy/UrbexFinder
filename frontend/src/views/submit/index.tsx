"use client";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { useSession } from "@/entities/session";
import { Place } from "@/entities/place";
import { PlaceForm } from "@/widgets/place-form";
export function SubmitView() {
  const { user, loading } = useSession(),
    [place, setPlace] = useState<Place | null>(null);
  return (
    <main className="page submit-page">
      <div className="routes-page-heading">
        <Link
          href="/"
          className="routes-back-map"
          aria-label="Вернуться к карте"
          title="Вернуться к карте"
        >
          <ArrowLeft size={24} aria-hidden="true" />
        </Link>
        <h1>{place ? "Заявка отправлена" : "Добавить место"}</h1>
      </div>
      {loading ? (
        <p>Загрузка…</p>
      ) : !user ? (
        <p>
          <Link href="/login?next=%2Fsubmit">Войдите или зарегистрируйтесь</Link>,
          чтобы отправить заявку.
        </p>
      ) : place ? (
        <>
          <p>«{place.name}» появится на карте после проверки.</p>
          <Link href="/account">Перейти к моим заявкам →</Link>
        </>
      ) : (
        <PlaceForm onSuccess={setPlace} />
      )}
    </main>
  );
}
