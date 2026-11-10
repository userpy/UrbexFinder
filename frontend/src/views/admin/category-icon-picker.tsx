"use client";
import { useEffect, useRef } from "react";
import { ChevronDown } from "lucide-react";
import { CategoryIcon, categoryVisuals } from "@/entities/place";

const labels: Record<keyof typeof categoryVisuals, string> = {
  other: "Разное", estate: "Усадьба", shelter: "Убежище",
  military: "Военный объект", camp: "Лагерь", school: "Учебное заведение",
  culture: "Культура", industry: "Промышленность", church: "Церковь",
  nature: "Природа", geocache: "Геокешинг", infrastructure: "Инфраструктура",
  architecture: "Архитектура",
  castle: "Замок",
  house: "Жилой дом",
  hospital: "Больница",
  hotel: "Гостиница",
  bridge: "Мост",
  railway: "Железная дорога",
  airport: "Аэродром",
  port: "Порт",
  lighthouse: "Маяк",
  water_tower: "Водонапорная башня",
  mine: "Шахта",
  quarry: "Карьер",
  cave: "Пещера",
  mountain: "Горы",
  waterfall: "Водопад",
  monument: "Памятник",
  cemetery: "Кладбище",
};
export function CategoryIconPicker({ value, category, onChange }: {
  value?: string | null;
  category?: string;
  onChange: (value: string) => void;
}) {
  const selectedIcon = value && Object.prototype.hasOwnProperty.call(categoryVisuals, value)
    ? value as keyof typeof categoryVisuals : "other";
  const menu = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (menu.current && !menu.current.contains(event.target as Node)) menu.current.open = false;
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, []);
  function choose(icon: string) {
    onChange(icon);
    if (menu.current) {
      menu.current.open = false;
      menu.current.querySelector("summary")?.focus();
    }
  }
  return (
    <div className="category-icon-field">
      <span>Иконка категории</span>
      <input type="hidden" name="icon" value={selectedIcon} />
      <details ref={menu} className="category-icon-picker" onKeyDown={(event) => {
        if (event.key === "Escape" && menu.current?.open) {
          event.preventDefault();
          event.stopPropagation();
          menu.current.open = false;
          menu.current.querySelector("summary")?.focus();
        }
      }}>
        <summary>
          <CategoryIcon category={category} icon={value} />
          <span>{labels[selectedIcon]}</span>
          <ChevronDown size={16} />
        </summary>
        <div className="category-icon-dropdown">
          <div className="category-icon-grid" role="group" aria-label="Выберите иконку категории">
            {(Object.keys(categoryVisuals) as Array<keyof typeof categoryVisuals>).map((icon) => (
              <button key={icon} type="button" title={labels[icon]}
                aria-label={labels[icon]} aria-pressed={selectedIcon === icon}
                onClick={() => choose(icon)}>
                <CategoryIcon category={labels[icon]} icon={icon} width={30} height={30} />
              </button>
            ))}
          </div>
        </div>
      </details>
    </div>
  );
}
