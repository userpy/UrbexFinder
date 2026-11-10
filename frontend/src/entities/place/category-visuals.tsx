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
  architecture: { color: "#d9b982", paths: ["M3 21h18M4 9h16L12 3Z", "M6 9v12M10 9v12M14 9v12M18 9v12"] },
  castle: { color: "#c5aed8", paths: ["M3 21V5h3v3h3V5h6v3h3V5h3v16Z", "M9 21v-6a3 3 0 0 1 6 0v6M7 11v2M17 11v2"] },
  house: { color: "#d4b090", paths: ["m3 11 9-8 9 8M5 10v11h14V10", "M10 21v-7h4v7"] },
  hospital: { color: "#d99797", paths: ["M5 21V3h14v18ZM3 21h18", "M9 8h6M12 5v6M10 21v-6h4v6"] },
  hotel: { color: "#c9a8c7", paths: ["M4 21V3h16v18ZM2 21h20", "M8 7h1M15 7h1M8 11h1M15 11h1M10 21v-6h4v6"] },
  bridge: { color: "#94b6d0", paths: ["M2 14h20M5 4v17M19 4v17", "M5 5q7 14 14 0M9 11v3M15 11v3M2 10l3-5M19 5l3 5"] },
  railway: { color: "#9cb9c6", paths: ["M6 17V5q0-2 6-2t6 2v12ZM6 10h12M12 3v7", "M8 14h1M15 14h1M8 17l-4 5M16 17l4 5M6 20h12"] },
  airport: { color: "#a3c8e1", paths: ["m12 3 2 7 7 4v3l-7-2v4l2 2H8l2-2v-4l-7 2v-3l7-4Z"] },
  port: { color: "#80bccd", paths: ["M12 3v17M9 5h6M4 13v4q8 8 16 0v-4", "m2 15 2-2 2 2M18 15l2-2 2 2M8 10h8"] },
  lighthouse: { color: "#e0b77a", paths: ["M7 21 9 9h6l2 12ZM8 5l4-3 4 3v4H8ZM6 21h12", "M9 15h6M2 5h3M19 5h3"] },
  water_tower: { color: "#8fbed0", paths: ["M6 4q6-4 12 0v7l-6 3-6-3ZM6 7h12", "M9 13 6 21M15 13l3 8M8 17h8M5 21h14"] },
  mine: { color: "#b7aa91", paths: ["M3 21v-9a9 9 0 0 1 18 0v9ZM7 21v-9a5 5 0 0 1 10 0v9", "M9 21l2-8M15 21l-2-8M10 17h4M9 20h6"] },
  quarry: { color: "#c7aa83", paths: ["M2 5h5v5h5v5h5v6h5M2 21h20", "M12 3h10M17 7h5M20 11h2"] },
  cave: { color: "#a8b1a2", paths: ["M2 21 5 8l7-5 7 5 3 13Z", "M8 21v-7l4-4 4 4v7M6 7l3 4M17 7l-2 3"] },
  mountain: { color: "#9bb7b4", paths: ["m2 21 8-16 5 10 3-6 4 12Z", "m7 11 3 2 3-2"] },
  waterfall: { color: "#83c7de", paths: ["M2 4h8v5q0 3-3 6t-2 6M22 4h-7v5q0 4 3 7v5", "M12 5v7l-2 5v4M2 9h4M19 9h3"] },
  monument: { color: "#c7c0b1", paths: ["M5 21h14v-3H5ZM8 18v-3h8v3M10 15V5l2-3 2 3v10", "M9 8h6"] },
  cemetery: { color: "#b3aac3", paths: ["M5 21V9a7 7 0 0 1 14 0v12ZM3 21h18", "M12 6v8M9 9h6M9 18h6"] },
} as const;

export function categoryVisual(icon?: string | null) {
  if (icon && Object.prototype.hasOwnProperty.call(categoryVisuals, icon)) {
    const key = icon as keyof typeof categoryVisuals;
    return { key, ...categoryVisuals[key] };
  }
  return { key: "other" as const, ...categoryVisuals.other };
}

export function CategoryIcon({
  category,
  icon,
  ...props
}: SVGProps<SVGSVGElement> & { category?: string | null; icon?: string | null }) {
  const visual = categoryVisual(icon);
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
