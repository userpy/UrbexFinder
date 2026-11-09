"use client";
import { CategoryFilter } from "./category-filter";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Search,
  MapPin,
  X,
  SlidersHorizontal,
  ArrowUpRight,
  Compass,
  Building2,
  TextSearch,
  Star,
  MessageSquare,
  Camera,
} from "lucide-react";
import {
  Place,
  Category,
  CategoryIcon,
  SearchLocation,
} from "@/entities/place";
import { api, Page } from "@/shared/api";
import type { FeatureCollection, Point } from "geojson";
import { MapPanel } from "@/widgets/map";
import { PlaceDetail } from "@/widgets/place-detail";
import {
  HighlightMatch,
  descriptionExcerpt,
} from "@/shared/ui/highlight-match";
import { Button } from "@/shared/ui/button";
export function Explorer() {
  const searchInput = useRef<HTMLInputElement>(null);
  const [places, setPlaces] = useState<Place[]>([]),
    [selected, setSelected] = useState<Place | null>(null),
    [categories, setCategories] = useState<Category[]>([]);
  const [query, setQuery] = useState(""),
    [category, setCategory] = useState(""),
    [bbox, setBbox] = useState(""),
    [page, setPage] = useState(1),
    [total, setTotal] = useState(0),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [mobile, setMobile] = useState("list"),
    [near, setNear] = useState<[number, number] | null>(null),
    [radius, setRadius] = useState("10"),
    [retry, setRetry] = useState(0);
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("place");
    if (!id || !/^\d+$/.test(id)) return;
    const abort = new AbortController();
    api<Place>(`/places/${id}`, { signal: abort.signal })
      .then((place) => {
        setSelected(place);
        setMobile("map");
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => abort.abort();
  }, []);
  const [resolvedQuery, setResolvedQuery] = useState("");
  const [locality, setLocality] = useState<SearchLocation | null>(null);
  const [locations, setLocations] = useState<SearchLocation[]>([]);
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const selectedBounds = useMemo<[number, number, number, number] | undefined>(
    () =>
      selected
        ? [
            selected.longitude - 0.005,
            selected.latitude - 0.005,
            selected.longitude + 0.005,
            selected.latitude + 0.005,
          ]
        : undefined,
    [selected],
  );
  const focusLocation = useCallback((location: SearchLocation) => {
    setSuggestionsOpen(false);
    setLocality(location);
    setBbox(location.bbox.join(","));
    setNear(null);
    setPage(1);
    setSelected(null);
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    const timer = setTimeout(
      async () => {
        try {
          setLocality(null);
          setLocations([]);
          setError("");
          if (query.trim()) {
            const result = await api<{ items: SearchLocation[] }>(
              `/search/locations?${new URLSearchParams({ q: query })}`,
              { signal: abort.signal },
            );
            if (abort.signal.aborted) return;
            setLocations(result.items);
          }
          setResolvedQuery(query);
        } catch (cause) {
          if (!abort.signal.aborted) {
            setError((cause as Error).message);
            setLoading(false);
          }
        }
      },
      query.trim() ? 300 : 0,
    );
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [query, retry]);
  const [zoom, setZoom] = useState(9),
    [mapData, setMapData] = useState<
      FeatureCollection<Point> & { total: number }
    >({ type: "FeatureCollection", features: [], total: 0 });
  useEffect(() => {
    api<Page<Category>>("/categories")
      .then((d) => setCategories(d.items))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (query !== resolvedQuery) return;
    const abort = new AbortController();
    const t = setTimeout(() => {
      setLoading(true);
      setError("");
      const params = new URLSearchParams({
        q: locality ? "" : query,
        search_in: "all",
        page: String(page),
        limit: "30",
      });
      if (locality) {
        params.set("locality", locality.query);
        params.set("locality_bbox", locality.bbox.join(","));
      }
      if (category) params.set("category_id", category);
      if (bbox && !near && (!query.trim() || locality))
        params.set("bbox", bbox);
      if (near) {
        params.set("near_lon", String(near[0]));
        params.set("near_lat", String(near[1]));
        params.set("radius_km", radius);
      }
      api<Page<Place>>(`/places?${params}`, { signal: abort.signal })
        .then((d) => {
          setPlaces(d.items);
          setTotal(d.total);
        })
        .catch((e) => {
          if (e.name !== "AbortError") setError(e.message);
        })
        .finally(() => {
          if (!abort.signal.aborted) setLoading(false);
        });
    }, 300);
    return () => {
      clearTimeout(t);
      abort.abort();
    };
  }, [
    query,
    resolvedQuery,
    locality,
    category,
    bbox,
    page,
    near,
    radius,
    retry,
  ]);
  useEffect(() => {
    if (!bbox || query !== resolvedQuery) return;
    const abort = new AbortController();
    const timer = setTimeout(() => {
      const params = new URLSearchParams({
        bbox,
        zoom: String(zoom),
        q: locality ? "" : query,
        search_in: "all",
      });
      if (locality) {
        params.set("locality", locality.query);
        params.set("locality_bbox", locality.bbox.join(","));
      }
      if (category) params.set("category_id", category);
      if (near) {
        params.set("near_lon", String(near[0]));
        params.set("near_lat", String(near[1]));
        params.set("radius_km", radius);
      }
      api<FeatureCollection<Point> & { total: number }>(`/map?${params}`, {
        signal: abort.signal,
      })
        .then(setMapData)
        .catch((e) => {
          if (e.name !== "AbortError") setError(e.message);
        });
    }, 200);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [
    bbox,
    zoom,
    query,
    resolvedQuery,
    locality,
    category,
    near,
    radius,
    retry,
  ]);
  async function choose(id: number) {
    try {
      const p =
        places.find((p) => p.id === id) || (await api<Place>(`/places/${id}`));
      setSelected(p);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <main className="explorer">
      <aside className={`catalog ${mobile === "map" ? "mobile-hidden" : ""}`}>
        <div className="catalog-heading">
          <div className="eyebrow">ТЕРРИТОРИЯ ИССЛЕДОВАНИЙ</div>
          <h1>
            Места вне маршрутов<span>.</span>
          </h1>
          <p>Сохраняем историю. Открываем забытое.</p>
        </div>
        <div className="filters">
          <div
            className="search"
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget))
                setSuggestionsOpen(false);
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") setSuggestionsOpen(false);
            }}
          >
            <Search size={17} />
            <input
              ref={searchInput}
              onFocus={() => setSuggestionsOpen(true)}
              aria-controls="search-suggestions"
              aria-label="Поиск мест"
              placeholder="Город, название или адрес"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setSuggestionsOpen(true);
                setLoading(true);
                setPage(1);
              }}
            />
            {query && (
              <button
                type="button"
                className="search-clear"
                aria-label="Очистить поиск"
                title="Очистить поиск"
                onClick={() => {
                  setQuery("");
                  setLocality(null);
                  setLocations([]);
                  setLoading(true);
                  setPage(1);
                  searchInput.current?.focus();
                }}
              >
                <X size={16} />
              </button>
            )}
            {suggestionsOpen && query.trim() && (
              <div
                id="search-suggestions"
                className="search-suggestions"
                aria-label="Варианты поиска"
              >
                {loading ||
                query !== resolvedQuery ||
                (!locations.length && (locality || !places.length)) ? (
                  <p role="status">Ищем</p>
                ) : (
                  <>
                    {locations.length
                      ? locations.map((location) => (
                          <button
                            type="button"
                            key={location.label}
                            onClick={() => focusLocation(location)}
                          >
                            <Building2
                              size={18}
                              aria-hidden="true"
                              className="suggestion-icon"
                            />
                            <span>
                              <strong>
                                <HighlightMatch
                                  text={location.label}
                                  query={query}
                                />
                              </strong>
                              <small>{location.count} мест в каталоге</small>
                            </span>
                          </button>
                        ))
                      : null}
                    {!locality && (
                      <>
                        {places.length
                          ? places.slice(0, 5).map((place) => (
                              <button
                                type="button"
                                key={place.id}
                                onClick={() => {
                                  setSuggestionsOpen(false);
                                  void choose(place.id);
                                }}
                              >
                                <TextSearch
                                  size={18}
                                  aria-hidden="true"
                                  className="suggestion-icon"
                                />
                                <span>
                                  <strong>
                                    <HighlightMatch
                                      text={place.name}
                                      query={query}
                                    />
                                  </strong>
                                  <small>
                                    <HighlightMatch
                                      text={place.region || ""}
                                      query={query}
                                    />
                                  </small>
                                  {place.description && (
                                    <small className="match-description">
                                      <HighlightMatch
                                        text={descriptionExcerpt(
                                          place.description,
                                          query,
                                        )}
                                        query={query}
                                      />
                                    </small>
                                  )}
                                </span>
                              </button>
                            ))
                          : null}
                      </>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
          {locality && !suggestionsOpen && (
            <div className="location-search" role="status">
              <strong>{locality.label}</strong>
              <button
                onClick={() => {
                  setSuggestionsOpen(true);
                  searchInput.current?.focus();
                }}
              >
                Выбрать другой населённый пункт
              </button>
            </div>
          )}
          <div className="filter-title">
            <SlidersHorizontal size={14} />
            фильтр{" "}
            <button
              onClick={() => {
                setQuery("");
                setCategory("");
                setNear(null);
                setPage(1);
              }}
            >
              Сбросить
            </button>
          </div>
          <div className="category-filter">
            <CategoryFilter categories={categories} value={category} onChange={(value) => {
              setCategory(value);
              setPage(1);
            }} />
          </div>
          {near && (
            <div className="near">
              <MapPin size={14} />
              Рядом с {near.map((n) => n.toFixed(3)).join(", ")}
              <select
                aria-label="Радиус"
                value={radius}
                onChange={(e) => {
                  setRadius(e.target.value);
                  setPage(1);
                }}
              >
                {[1, 5, 10, 25, 50, 100].map((r) => (
                  <option key={r} value={r}>
                    {r} км
                  </option>
                ))}
              </select>
              <button onClick={() => setNear(null)}>×</button>
            </div>
          )}
        </div>
        <div className="results-label">
          <span>
            {loading ? "Поиск объектов…" : `${total} объектов найдено`}
          </span>
          <span>СТР. {page}</span>
        </div>
        <div className="place-list" aria-busy={loading}>
          {error ? (
            <div className="empty">
              <p>{error}</p>
              <Button onClick={() => setRetry((v) => v + 1)}>Повторить</Button>
            </div>
          ) : loading ? (
            <div className="skeletons">
              {[1, 2, 3, 4].map((n) => (
                <div key={n} />
              ))}
            </div>
          ) : places.length ? (
            places.map((p, i) => (
              <button
                key={p.id}
                onClick={() => choose(p.id)}
                className={`place-row ${selected?.id === p.id ? "selected" : ""}`}
              >
                <div className="row-icon">
                  <CategoryIcon
                    category={
                      categories.find((c) => c.id === p.category_id)?.name ||
                      p.category
                    }
                  />
                </div>
                <div>
                  <small>
                    {categories.find((c) => c.id === p.category_id)?.name ||
                      "Объект"}{" "}
                    <span>
                      {" "}
                      / {String(i + 1 + (page - 1) * 30).padStart(2, "0")}
                    </span>
                  </small>
                  <h2>
                    <HighlightMatch text={p.name} query={query} />
                  </h2>
                  <p>
                    <MapPin size={12} />
                    {p.region}
                  </p>
                  {query.trim() && !locality && p.description && (
                    <p className="match-description">
                      <HighlightMatch
                        text={descriptionExcerpt(p.description, query)}
                        query={query}
                      />
                    </p>
                  )}
                  <div className="place-stats">
                    {!!p.rating_count && (
                      <span
                        className="place-rating"
                        title={`${p.rating_count} оценок`}
                        aria-label={`Рейтинг ${p.rating_avg?.toFixed(1)} из 5, оценок: ${p.rating_count}`}
                      >
                        <Star
                          size={13}
                          aria-hidden="true"
                          fill="currentColor"
                        />
                        {p.rating_avg?.toFixed(1)} · {p.rating_count}
                      </span>
                    )}
                    {!!p.reviews_count && (
                      <span
                        aria-label={`Отзывов: ${p.reviews_count}`}
                        title="Отзывы"
                      >
                        <MessageSquare size={13} aria-hidden="true" />
                        {p.reviews_count}
                      </span>
                    )}
                    {!!p.photos_count && (
                      <span aria-label={`Фото: ${p.photos_count}`} title="Фото">
                        <Camera size={13} aria-hidden="true" />
                        {p.photos_count}
                      </span>
                    )}
                  </div>
                </div>
                <ArrowUpRight size={16} className="row-arrow" />
              </button>
            ))
          ) : (
            <div className="empty">
              <Search size={30} />
              <h3>Здесь пока тихо</h3>
              <p>Измените область карты или ослабьте фильтры.</p>
            </div>
          )}
        </div>
        <div className="pager">
          <button
            disabled={page === 1 || loading}
            onClick={() => setPage((v) => v - 1)}
          >
            ← Назад
          </button>
          <span>
            {page} / {Math.max(1, Math.ceil(total / 30))}
          </span>
          <button
            disabled={page * 30 >= total || loading}
            onClick={() => setPage((v) => v + 1)}
          >
            Далее →
          </button>
        </div>
      </aside>
      <section
        className={`map-section ${mobile === "list" ? "mobile-hidden" : ""}`}
      >
        <MapPanel
          data={mapData}
          focusBounds={selectedBounds ?? locality?.bbox}
          places={places}
          selected={selected?.id || null}
          onSelect={choose}
          onBounds={(b, z) => {
            setBbox(b);
            setZoom(z);
            setPage(1);
          }}
          onPoint={(lon, lat) => {
            setNear([lon, lat]);
            setPage(1);
          }}
        />
        <div className="map-bottom">
          <span>
            <i /> ОПУБЛИКОВАННЫЕ ОБЪЕКТЫ
          </span>
          <span>На карте — {mapData.total} объектов в области</span>
        </div>
      </section>
      {selected ? (
        <PlaceDetail
          key={selected.id}
          place={selected}
          onClose={() => setSelected(null)}
        />
      ) : (
        <aside className="detail detail-idle">
          <Compass size={42} />
          <span className="eyebrow">НАЧНИТЕ ИССЛЕДОВАНИЕ</span>
          <h2>
            У каждого места
            <br />
            есть своя история
          </h2>
          <p>Выберите объект на карте или в списке, чтобы узнать больше.</p>
          <div className="idle-line" />
          <small>Координаты не означают разрешение на посещение.</small>
        </aside>
      )}
      <div className="mobile-switch">
        <button
          className={mobile === "list" ? "active" : ""}
          onClick={() => setMobile("list")}
        >
          Список
        </button>
        <button
          className={mobile === "map" ? "active" : ""}
          onClick={() => setMobile("map")}
        >
          Карта
        </button>
      </div>
    </main>
  );
}
