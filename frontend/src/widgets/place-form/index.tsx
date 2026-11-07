"use client";
import { useEffect, useMemo, useState } from "react";
import { Place, Category } from "@/entities/place";
import { api, body, Page } from "@/shared/api";
import { MapPanel } from "@/widgets/map";
import { Button } from "@/shared/ui/button";
export function PlaceForm({
  initial,
  onSuccess,
}: {
  initial?: Place;
  onSuccess: (place: Place) => void;
}) {
  const [categories, setCategories] = useState<Category[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [categoryId, setCategoryId] = useState(
    String(initial?.category_id ?? ""),
  );
  const [region, setRegion] = useState(initial?.region ?? "");
  const [geocoding, setGeocoding] = useState(false);
  const [latitude, setLatitude] = useState(String(initial?.latitude ?? ""));
  const [longitude, setLongitude] = useState(String(initial?.longitude ?? ""));
  const valid =
    latitude !== "" &&
    longitude !== "" &&
    Number.isFinite(Number(latitude)) &&
    Number.isFinite(Number(longitude)) &&
    Math.abs(Number(latitude)) <= 85 &&
    Math.abs(Number(longitude)) <= 180;
  const validationMessage =
    name.trim().length < 3 || name.trim().length > 200
      ? "Название должно содержать от 3 до 200 символов."
      : description.trim().length < 20 || description.trim().length > 20000
        ? `Описание должно содержать от 20 до 20 000 символов. Сейчас: ${description.trim().length}.`
        : !valid
          ? "Выберите место на карте, чтобы заполнить координаты."
          : region.trim().length < 2 || region.trim().length > 200
            ? "Нажмите «Определить регион по координатам»."
            : !categories.some((category) => String(category.id) === categoryId)
              ? "Выберите категорию места."
              : "";
  const formValid = !validationMessage;
  const lat = valid ? Number(latitude) : (initial?.latitude ?? 55.75);
  const lon = valid ? Number(longitude) : (initial?.longitude ?? 37.62);
  const point = useMemo<Place>(
    () => ({
      id: initial?.id ?? 0,
      name: initial?.name ?? "Новое место",
      description: "",
      latitude: lat,
      longitude: lon,
      region: "",
      category_id: 0,
      condition: "unknown",
      access: "",
      author_id: null,
      status: "pending",
      created_at: "",
      updated_at: "",
    }),
    [initial?.id, initial?.name, lat, lon],
  );
  const bounds = useMemo<[number, number, number, number]>(
    () => [lon - 0.01, lat - 0.01, lon + 0.01, lat + 0.01],
    [lat, lon],
  );
  useEffect(() => {
    api<Page<Category>>("/categories")
      .then((d) => setCategories(d.items))
      .catch((e) => setError(e.message));
  }, []);
  return (
    <form
      className="place-form"
      onSubmit={async (e) => {
        e.preventDefault();
        if (busy || geocoding || !formValid) return;
        setBusy(true);
        setError("");
        const f = new FormData(e.currentTarget);
        const data = Object.fromEntries(f);
        try {
          const place = await api<Place>(
            initial ? `/places/${initial.id}` : "/places",
            {
              method: initial ? "PUT" : "POST",
              body: body({
                ...data,
                name: name.trim(),
                description: description.trim(),
                region: region.trim(),
                condition: initial?.condition ?? "unknown",
                access:
                  initial?.access ?? "Сведения о доступе не подтверждены.",
                latitude: Number(latitude),
                longitude: Number(longitude),
                category_id: Number(data.category_id),
              }),
            },
          );
          onSuccess(place);
        } catch (e) {
          setError((e as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <label>
        Название
        <input
          name="name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          minLength={3}
          maxLength={200}
          placeholder="Например, старая водонапорная башня"
          required
        />
      </label>
      <label>
        Описание
        <textarea
          name="description"
          aria-describedby="place-description-hint"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          minLength={20}
          maxLength={20000}
          rows={5}
          placeholder="История места, что сохранилось, источники сведений"
          required
        />
      </label>
      <p id="place-description-hint" className="muted">
        Минимум 20 символов · Введено: {description.trim().length}
      </p>
      <p className="muted">
        Перетащите метку на карте — широта и долгота заполнятся автоматически.
      </p>
      <div className="place-form-map">
        <MapPanel
          places={[point]}
          selected={point.id}
          onSelect={() => {}}
          editable
          markerDisabled={busy || geocoding}
          center={[lon, lat]}
          focusBounds={bounds}
          pointHint="Перетащите метку, чтобы изменить координаты"
          onPoint={(lng, lat) => {
            if (!busy && !geocoding) {
              setRegion("");
              setLatitude(lat.toFixed(6));
              setLongitude(lng.toFixed(6));
            }
          }}
        />
      </div>
      <div className="form-grid">
        <p className="place-coordinate">
          Широта: <output>{latitude || "—"}</output>
        </p>
        <p className="place-coordinate">
          Долгота: <output>{longitude || "—"}</output>
        </p>
        <div>
          <p className="place-coordinate">
            Регион: <output>{region || "—"}</output>
          </p>
          <Button
            type="button"
            variant="outline"
            disabled={busy || geocoding || !valid}
            onClick={async () => {
              setGeocoding(true);
              setError("");
              try {
                const result = await api<{ region: string }>(
                  `/geocode/reverse?latitude=${lat}&longitude=${lon}`,
                );
                setRegion(result.region);
              } catch (error) {
                setError((error as Error).message);
              } finally {
                setGeocoding(false);
              }
            }}
          >
            {geocoding
              ? "Определение региона…"
              : "Определить регион по координатам"}
          </Button>
        </div>
        <label>
          Категория
          <select
            name="category_id"
            value={categoryId}
            onChange={(e) => setCategoryId(e.target.value)}
            required
          >
            <option value="" disabled>
              Выберите категорию
            </option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && (
        <p className="notice" role="alert">
          {error}
        </p>
      )}
      {validationMessage && (
        <p id="place-validation" className="notice" role="status">
          {validationMessage}
        </p>
      )}
      <Button
        aria-describedby={validationMessage ? "place-validation" : undefined}
        disabled={busy || geocoding || !formValid}
      >
        {busy ? "Отправка…" : "Отправить на проверку"}
      </Button>
    </form>
  );
}
