"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";

const statuses = [
  { value: "planned", label: "Планирую" },
  { value: "visited", label: "Посетил" },
  { value: "skipped", label: "Пропустил" },
] as const;
export type StopStatus = (typeof statuses)[number]["value"];

export function StatusPicker({ value, onChange, disabled }: {
  value: StopStatus;
  onChange: (value: StopStatus) => void;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const options = useRef<(HTMLButtonElement | null)[]>([]);
  const id = useId();
  const selected = statuses.findIndex((status) => status.value === value);
  const visible = open && !disabled;
  useEffect(() => {
    if (!visible) return;
    options.current[selected]?.focus();
    const dismiss = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [visible, selected]);
  function close() {
    setOpen(false);
    trigger.current?.focus();
  }
  return (
    <div ref={root} className="route-status-picker"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && visible) {
          event.preventDefault();
          event.stopPropagation();
          close();
        }
      }}>
      <button ref={trigger} type="button" className="route-status-trigger"
        disabled={disabled} aria-label={`Статус точки: ${statuses[selected].label}`}
        aria-haspopup="listbox" aria-expanded={visible} aria-controls={visible ? id : undefined}
        onClick={() => setOpen(!open)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
          }
        }}>
        <span>{statuses[selected].label}</span><ChevronDown size={14} aria-hidden="true" />
      </button>
      {visible && <div id={id} role="listbox" aria-label="Статус точки" className="route-status-options">
        {statuses.map((status, index) => <button type="button" role="option"
          key={status.value} aria-selected={value === status.value} tabIndex={-1}
          ref={(element) => { options.current[index] = element; }}
          onClick={() => { onChange(status.value); close(); }}
          onKeyDown={(event) => {
            const next = event.key === "Home" ? 0 : event.key === "End" ? 2
              : event.key === "ArrowDown" ? (index + 1) % 3
              : event.key === "ArrowUp" ? (index + 2) % 3 : -1;
            if (next >= 0) { event.preventDefault(); options.current[next]?.focus(); }
          }}>
          <span>{status.label}</span>{value === status.value && <Check size={14} aria-hidden="true" />}
        </button>)}
      </div>}
    </div>
  );
}
