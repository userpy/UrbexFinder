import { Star } from "lucide-react";

export function PlaceRating({
  ratingAverage = 0,
  ratingCount = 0,
}: {
  ratingAverage?: number;
  ratingCount?: number;
}) {
  if (ratingCount <= 0) return null;

  const rating = ratingCount > 0 ? Math.min(5, Math.max(0, ratingAverage)) : 0;
  return (
    <div
      className="gallery-rating"
      aria-label={`Рейтинг места: ${rating.toFixed(1)} из 5, оценок: ${ratingCount}`}
      title="Рейтинг места"
    >
      <span className="gallery-rating-stars" aria-hidden="true">
        {Array.from({ length: 5 }, (_, index) => (
          <span className="gallery-rating-star" key={index}>
            <Star size={14} />
            <span
              style={{
                width: `${Math.min(1, Math.max(0, rating - index)) * 100}%`,
              }}
            >
              <Star size={14} fill="currentColor" />
            </span>
          </span>
        ))}
      </span>
      <strong>{rating.toFixed(1)}</strong>
      <span>{ratingCount > 0 ? `Оценок: ${ratingCount}` : "Нет оценок"}</span>
    </div>
  );
}
