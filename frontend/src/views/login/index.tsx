"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Compass, ArrowRight } from "lucide-react";
import { useSession } from "@/entities/session";
import { api, body, setCsrf } from "@/shared/api";
import { Button } from "@/shared/ui/button";
export function LoginView() {
  const [method, setMethod] = useState<"telegram" | "password" | null>(null);
  const [register, setRegister] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const { refresh } = useSession(),
    router = useRouter();
  const [telegram, setTelegram] = useState<{
    url: string;
    code: string;
    expires: number;
  } | null>(null);
  useEffect(() => {
    if (!telegram) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      if (Date.now() > telegram!.expires) {
        setTelegram(null);
        setError("Подтверждение истекло. Начните вход заново.");
        return;
      }
      try {
        const result = await api<{ pending?: boolean; csrf?: string }>(
          "/auth/telegram/complete",
          { method: "POST", signal: abort.signal },
        );
        if (abort.signal.aborted) return;
        if (result.pending) {
          timer = setTimeout(poll, 2000);
          return;
        }
        if (result.csrf) setCsrf(result.csrf);
        await refresh();
        router.replace("/");
        setTelegram(null);
      } catch (error) {
        if (!abort.signal.aborted) {
          setError((error as Error).message);
          setTelegram(null);
        }
      }
    }
    timer = setTimeout(poll, 2000);
    return () => {
      abort.abort();
      clearTimeout(timer);
    };
  }, [telegram, refresh, router]);
  return (
    <main className="auth-page">
      <div className="auth-intro">
        <Compass size={50} />
        <div className="eyebrow">ЛИЧНЫЙ АТЛАС</div>
        <h1>
          Открывайте места.
          <br />
          Сохраняйте истории.
        </h1>
        <p>Избранное, наблюдения и новые точки на карте — в вашем кабинете.</p>
      </div>
      <div className="auth-card">
        <div className="tabs">
          <button
            className={!register ? "active" : ""}
            onClick={() => setRegister(false)}
          >
            Вход
          </button>
          <button
            className={register ? "active" : ""}
            onClick={() => setRegister(true)}
          >
            Регистрация
          </button>
        </div>
        <h2>{register ? "Стать исследователем" : "С возвращением"}</h2>
        <div className="auth-methods" role="group" aria-label="Способ входа">
          <Button
            type="button"
            variant={method === "telegram" ? "default" : "outline"}
            disabled={busy}
            aria-pressed={method === "telegram"}
            onClick={async () => {
              setMethod("telegram");
              setBusy(true);
              setError("");
              setTelegram(null);
              try {
                const result = await api<{ url: string; code: string }>(
                  "/auth/telegram/start",
                  { method: "POST" },
                );
                setTelegram({ ...result, expires: Date.now() + 300000 });
              } catch (error) {
                setError((error as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            Войти через Telegram
          </Button>
          <Button
            type="button"
            variant={method === "password" ? "default" : "outline"}
            disabled={busy}
            aria-pressed={method === "password"}
            onClick={() => {
              setMethod("password");
              setTelegram(null);
              setError("");
            }}
          >
            Логин и пароль
          </Button>
        </div>
        {!method && (
          <p className="muted">
            Выберите удобный способ {register ? "регистрации" : "входа"}.
          </p>
        )}
        {method === "telegram" && (
          <div className="telegram-login">
            {telegram && (
              <div role="status">
                <p>
                  Код подтверждения: <strong>{telegram.code}</strong>
                </p>
                <a href={telegram.url} target="_blank" rel="noreferrer">
                  Открыть Telegram →
                </a>
                <p>
                  Нажмите «Старт» в боте, сверьте код и подтвердите вход. Затем
                  вернитесь сюда — вход завершится автоматически. Ссылка
                  действует 5 минут.
                </p>
                <button type="button" onClick={() => setTelegram(null)}>
                  Отменить
                </button>
              </div>
            )}
          </div>
        )}
        {method === "password" && (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError("");
              const f = new FormData(e.currentTarget);
              try {
                const d = await api<{ csrf: string }>(
                  `/auth/${register ? "register" : "login"}`,
                  { method: "POST", body: body(Object.fromEntries(f)) },
                );
                setCsrf(d.csrf);
                await refresh();
                const next =
                  new URLSearchParams(window.location.search).get("next") || "";
                router.push(
                  /^\/routes(?:\?add=\d+)?$/.test(next) ? next : "/account",
                );
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            {register && (
              <label>
                Имя
                <input
                  name="name"
                  autoComplete="name"
                  minLength={2}
                  maxLength={100}
                  required
                />
              </label>
            )}
            <label>
              Email
              <input name="email" type="email" autoComplete="email" required />
            </label>
            <label>
              Пароль
              <input
                name="password"
                type="password"
                minLength={12}
                maxLength={128}
                autoComplete={register ? "new-password" : "current-password"}
                required
              />
            </label>
            <small className="muted">Не менее 12 символов</small>
            <Button disabled={busy}>
              {busy ? "Подождите…" : register ? "Создать аккаунт" : "Войти"}
              <ArrowRight size={16} />
            </Button>
          </form>
        )}
        {error && (
          <p role="alert" className="notice">
            {error}
          </p>
        )}
        <p className="muted">Для просмотра карты регистрация не нужна.</p>
      </div>
    </main>
  );
}
