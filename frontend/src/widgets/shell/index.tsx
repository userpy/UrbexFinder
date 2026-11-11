"use client";
import Link from "next/link";
import { Compass, Map, Plus, Route, UserRound, ShieldCheck } from "lucide-react";
import { useSession } from "@/entities/session";
export function Header() {
  const { user } = useSession();
  return (
    <header className="header">
      <Link href="/" className="brand">
        <Compass size={25} />
        <span>
          URBEX<span className="brand-light">FINDER</span>
          <small>АТЛАС ЗАБЫТЫХ МЕСТ</small>
        </span>
      </Link>
      <nav>
        <Link href="/">
          <Map size={16} />
          Карта
        </Link>
        {user && (
          <>
            <Link href="/routes">
              <Route size={16} aria-hidden="true" />
              Мои маршруты
            </Link>
            <Link href="/submit">
              <Plus size={16} />
              Добавить место
            </Link>
          </>
        )}
        {user && user.role !== "user" && (
          <Link href="/admin">
            <ShieldCheck size={16} />
            Управление
          </Link>
        )}
        <Link href={user ? "/account" : "/login"}>
          <UserRound size={16} />
          {user ? user.name : "Войти"}
        </Link>
      </nav>
    </header>
  );
}
