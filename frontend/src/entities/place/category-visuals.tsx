import type { SVGProps } from "react";

// One set of shapes and colors for list badges and MapLibre marker images.
export const categoryVisuals = {
  other: {
    color: "#b4becb",
    paths: ["M12 3 21 12 12 21 3 12Z", "M12 8v.01M12 11v5"],
  },
  estate: {
    color: "#dfb572",
    paths: [
      "M3 21h18M5 21V10h14v11M3 10l9-7 9 7Z",
      "M9 21v-6h6v6M8 12h.01M16 12h.01",
    ],
  },
  shelter: {
    color: "#a4b391",
    paths: ["M3 20v-7a9 9 0 0 1 18 0v7Z", "M8 20v-8h8v8M10 8h4M11 16h2"],
  },
  military: {
    color: "#c5938a",
    paths: [
      "M12 3 21 7v5c0 5-9 9-9 9S3 17 3 12V7Z",
      "m12 7 1.5 3 3.5.5-2.5 2.5.5 3.5-3-1.5-3 1.5.5-3.5L7 10.5l3.5-.5Z",
    ],
  },
  camp: {
    color: "#e7a47d",
    paths: ["M3 21 12 3l9 18ZM8 21l4-8 4 8M10 3l2 3 2-3"],
  },
  school: {
    color: "#8cb8df",
    paths: ["m2 9 10-5 10 5-10 5ZM6 11v6q6 5 12 0v-6M22 9v7"],
  },
  culture: {
    color: "#c6a4dc",
    paths: ["M3 21h18M5 21V9h14v12M3 9l9-6 9 6ZM9 12v6M15 12v6"],
  },
  industry: {
    color: "#daa16d",
    paths: ["M3 21V8h4v6l7-4v4l7-4v11ZM7 8V3H3v5M7 17h1M12 17h1M17 17h1"],
  },
  church: {
    color: "#e6cc89",
    paths: ["M12 2v6M9 5h6M5 21V12l7-5 7 5v9ZM10 21v-6h4v6M3 21h18"],
  },
  nature: { color: "#85c5a2", paths: ["m12 3-6 7h3l-5 7h6v4h4v-4h6l-5-7h3Z"] },
  geocache: {
    color: "#81c9ce",
    paths: [
      "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18",
      "m16 8-2.5 5.5L8 16l2.5-5.5Z",
    ],
  },
  infrastructure: {
    color: "#99a8dd",
    paths: ["M3 21 8 3M21 21 16 3M12 4v3M12 11v3M12 18v3"],
  },
} as const;

export function categoryVisual(name?: string | null, icon?: string | null) {
  if (icon && Object.prototype.hasOwnProperty.call(categoryVisuals, icon)) {
    const key = icon as keyof typeof categoryVisuals;
    return { key, ...categoryVisuals[key] };
  }
  const value = (name || "").toLocaleLowerCase("ru").replace(/ё/g, "е");
  const key = /усадьб|санатор|дом[а]? отдыха|архитектур/.test(value)
    ? "estate"
    : /бомбоубеж|убежищ|бункер/.test(value)
      ? "shelter"
      : /военн/.test(value)
        ? "military"
        : /лагер/.test(value)
          ? "camp"
          : /школ|колледж|институт|университет/.test(value)
            ? "school"
            : /культур|театр/.test(value)
              ? "culture"
              : /технолог|промышлен|завод|фабрик/.test(value)
                ? "industry"
                : /церк|храм|монастыр/.test(value)
                  ? "church"
                  : /природ|парк|лес/.test(value)
                    ? "nature"
                    : /geocach|геокеш/.test(value)
                      ? "geocache"
                      : /инфраструктур|мост|транспорт/.test(value)
                        ? "infrastructure"
                        : "other";
  return { key, ...categoryVisuals[key] };
}

export function CategoryIcon({
  category,
  icon,
  ...props
}: SVGProps<SVGSVGElement> & { category?: string | null; icon?: string | null }) {
  const visual = categoryVisual(category, icon);
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke={visual.color}
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      role="img"
      aria-label={category || "Другое"}
      data-category-icon={visual.key}
      {...props}
    >
      {visual.paths.map((d, i) => (
        <path key={i} d={d} />
      ))}
    </svg>
  );
}

export function categoryMarkerSvg(key: keyof typeof categoryVisuals) {
  const visual = categoryVisuals[key];
  return `<svg xmlns="http://www.w3.org/2000/svg" width="72" height="72" viewBox="0 0 36 36"><circle cx="18" cy="18" r="16" fill="#17212b" stroke="${visual.color}" stroke-width="1.6"/><g transform="translate(7 7) scale(.9167)" fill="none" stroke="${visual.color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${visual.paths.map((d) => `<path d="${d}"/>`).join("")}</g></svg>`;
}
