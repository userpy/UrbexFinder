export type Place = {
  id: number;
  name: string;
  description: string;
  latitude: number;
  longitude: number;
  region: string;
  full_address?: string | null;
  category_id: number;
  category?: string | null;
  category_icon?: string | null;
  rating_avg?: number;
  rating_count?: number;
  reviews_count?: number;
  photos_count?: number;
  condition: string;
  access: string;
  author_id: number | null;
  status: string;
  reason?: string;
  created_at: string;
  updated_at: string;
};
export type Category = { id: number; name: string; active: boolean; icon?: string | null };
export type Photo = {
  id: number;
  place_id: number;
  status: string;
  reason: string;
};
export type Review = {
  id: number;
  author_id: number | null;
  author_name?: string | null;
  source?: "website" | "telegram";
  text: string;
  score: number | null;
  status: string;
  reason: string;
};
export const conditions: Record<string, string> = {
  unknown: "Неизвестно",
  standing: "Сохранился",
  ruined: "Частично разрушен",
  demolished: "Снесён",
};
export const statuses: Record<string, string> = {
  pending: "На проверке",
  published: "Опубликовано",
  rejected: "Отклонено",
  changes_requested: "Нужны уточнения",
};

export {
  CategoryIcon,
  categoryVisual,
  categoryVisuals,
  categoryMarkerSvg,
} from "./category-visuals";

export type SearchLocation = {
  name: string;
  label: string;
  query: string;
  bbox: [number, number, number, number];
  count: number;
  source: "catalog";
};
