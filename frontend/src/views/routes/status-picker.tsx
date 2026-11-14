"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
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
  const [menuPosition, setMenuPosition] = useState<{
    top?: number;
    bottom?: number;
    left: number;
    maxHeight: number;
  } | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const options = useRef<(HTMLButtonElement | null)[]>([]);
  const id = useId();
  const selected = statuses.findIndex((status) => status.value === value);
  const visible = open && !disabled;
  useEffect(() => {
    if (!visible) return;
    options.current[selected]?.focus();
    const dismiss = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node) || (
        !root.current?.contains(target) && !menu.current?.contains(target)
      )) setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [visible, selected]);
  useLayoutEffect(() => {
    if (!visible) return;
    const updatePosition = () => {
      const triggerRect = trigger.current?.getBoundingClientRect();
      const menuElement = menu.current;
      if (!triggerRect || !menuElement) return;

      const gap = 4;
      const spaceBelow = window.innerHeight - triggerRect.bottom - gap;
      const spaceAbove = triggerRect.top - gap;
      const opensUp = spaceBelow < menuElement.scrollHeight && spaceAbove > spaceBelow;
      const maxHeight = Math.max(0, opensUp ? spaceAbove : spaceBelow);
      setMenuPosition({
        ...(opensUp
          ? { bottom: window.innerHeight - triggerRect.top + gap }
          : { top: triggerRect.bottom + gap }),
        left: Math.max(8, Math.min(triggerRect.left, window.innerWidth - 148)),
        maxHeight,
      });
    };

    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [visible]);
  function close() {
    setOpen(false);
    trigger.current?.focus();
  }
  return (
    <div ref={root} className="route-status-picker"
      onBlur={(event) => {
        const target = event.relatedTarget;
        if (!(target instanceof Node) || (
          !event.currentTarget.contains(target) && !menu.current?.contains(target)
        )) setOpen(false);
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
      {visible && createPortal(<div ref={menu} id={id} role="listbox"
        aria-label="Статус точки" className="route-status-options"
        style={menuPosition ?? undefined}>
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
      </div>, document.body)}
    </div>
  );
}
