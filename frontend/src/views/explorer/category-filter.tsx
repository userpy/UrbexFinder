"use client";

import { useId, useRef, useState } from "react";
import { Check, ChevronDown, Shapes } from "lucide-react";
import { CategoryIcon, type Category } from "@/entities/place";

export function CategoryFilter({
  categories,
  value,
  onChange,
}: {
  categories: Category[];
  value: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const options = useRef<(HTMLButtonElement | null)[]>([]);
  const id = useId();
  const items = [
    { id: "", name: "Все категории", icon: null },
    ...categories
      .filter(
        (category) => category.name.trim().toLocaleLowerCase("ru") !== "другое",
      )
      .map((c) => ({ ...c, id: String(c.id) })),
  ];
  const selected = Math.max(
    0,
    items.findIndex((item) => item.id === value),
  );
  function focus(index: number) {
    options.current[(index + items.length) % items.length]?.focus();
  }
  function close() {
    setOpen(false);
    trigger.current?.focus();
  }
  function icon(index: number) {
    return index === 0 ? (
      <Shapes size={18} aria-hidden="true" />
    ) : (
      <CategoryIcon
        category={items[index].name}
        icon={items[index].icon}
        width={18}
        height={18}
      />
    );
  }
  return (
    <div
      className="category-picker"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.preventDefault();
          event.stopPropagation();
          close();
        }
      }}
    >
      <button
        ref={trigger}
        type="button"
        className="category-picker-trigger"
        aria-label="Категория"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
        onKeyDown={(event) => {
          if (["ArrowDown", "ArrowUp"].includes(event.key)) {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        {icon(selected)}
        <span>{items[selected].name}</span>
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <div
          id={id}
          role="listbox"
          aria-label="Категория"
          className="category-picker-options"
        >
          {items.map((item, index) => (
            <button
              type="button"
              role="option"
              aria-selected={value === item.id}
              key={item.id}
              ref={(element) => {
                options.current[index] = element;
                if (element && index === selected) element.focus();
              }}
              tabIndex={index === selected ? 0 : -1}
              onClick={() => {
                onChange(item.id);
                close();
              }}
              onKeyDown={(event) => {
                if (
                  ["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)
                ) {
                  event.preventDefault();
                  focus(
                    event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? items.length - 1
                        : index + (event.key === "ArrowDown" ? 1 : -1),
                  );
                } else if (
                  event.key.length === 1 &&
                  event.key !== " " &&
                  !event.ctrlKey &&
                  !event.metaKey &&
                  !event.altKey
                ) {
                  const match = items.findIndex((_, offset) =>
                    items[(index + 1 + offset) % items.length].name
                      .toLocaleLowerCase()
                      .startsWith(event.key.toLocaleLowerCase()),
                  );
                  if (match >= 0) {
                    event.preventDefault();
                    focus(index + 1 + match);
                  }
                }
              }}
            >
              {icon(index)}
              <span>{item.name}</span>
              {value === item.id && <Check size={14} aria-hidden="true" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
