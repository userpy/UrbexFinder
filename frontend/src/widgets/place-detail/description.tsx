"use client";

import {
  createElement,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";

const subscribe = () => () => {};
const clientSnapshot = () => true;
const serverSnapshot = () => false;
const allowedTags = new Set([
  "p",
  "div",
  "br",
  "strong",
  "b",
  "em",
  "i",
  "u",
  "s",
  "del",
  "blockquote",
  "ul",
  "ol",
  "li",
  "h2",
  "h3",
  "h4",
  "pre",
  "code",
  "hr",
]);
const hiddenTags = new Set([
  "script",
  "style",
  "noscript",
  "iframe",
  "object",
  "embed",
  "svg",
  "math",
  "template",
]);

function safeHref(value: string): string | undefined {
  try {
    const url = new URL(value);
    if (["https:", "http:", "mailto:", "tel:"].includes(url.protocol))
      return url.href;
  } catch {
    // Relative and malformed links have no reliable destination in imported descriptions.
  }
}

function linkify(text: string, key: string): ReactNode[] {
  const result: ReactNode[] = [];
  let offset = 0;
  // Imported descriptions may mix Markdown links and escaped HTML breaks.
  const tokens =
    /\[([^\]\n]+)\]\(([^\s<>]+)\)|\\?<br\s*\/?\\?>|https?:\/\/[^\s<>"']+/gi;
  for (const match of text.matchAll(tokens)) {
    const start = match.index!;
    result.push(text.slice(offset, start));
    if (/^\\?<br/i.test(match[0])) {
      result.push(<br key={`${key}-${start}`} />);
      offset = start + match[0].length;
      continue;
    }
    const markdown = match[1] !== undefined;
    const candidate = markdown
      ? match[2]
      : match[0].replace(/[.,!?;:)}\]]+$/, "");
    const label = markdown ? match[1] : candidate;
    const href = safeHref(candidate);
    result.push(
      href ? (
        <a
          key={`${key}-${start}`}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
        >
          {label}
        </a>
      ) : (
        label
      ),
    );
    offset = start + (markdown ? match[0].length : candidate.length);
  }
  result.push(text.slice(offset));
  return result;
}

export function renderDescription(source: string): ReactNode[] {
  const document = new DOMParser().parseFromString(
    source.replace(/\\(<br\s*\/?)(?:\\)?(>)/gi, "$1$2"),
    "text/html",
  );
  function render(
    node: Node,
    key: string,
    insideLink = false,
    insideCode = false,
  ): ReactNode {
    if (node.nodeType === 3) {
      const text = node.textContent || "";
      return insideLink || insideCode ? text : linkify(text, key);
    }
    if (node.nodeType !== 1) return null;
    const element = node as Element;
    const tag = element.tagName.toLowerCase();
    if (hiddenTags.has(tag)) return null;
    const children = Array.from(element.childNodes, (child, index) =>
      render(
        child,
        `${key}-${index}`,
        insideLink || tag === "a",
        insideCode || tag === "code" || tag === "pre",
      ),
    );
    if (tag === "a") {
      const href = safeHref(element.getAttribute("href") || "");
      return href ? (
        <a key={key} href={href} target="_blank" rel="noopener noreferrer">
          {children}
        </a>
      ) : (
        children
      );
    }
    // Build new React elements; never forward source attributes or raw HTML.
    return allowedTags.has(tag)
      ? createElement(
          tag,
          { key },
          tag === "br" || tag === "hr" ? undefined : children,
        )
      : children;
  }
  return Array.from(document.body.childNodes, (node, index) =>
    render(node, String(index)),
  );
}

export function PlaceDescription({ description }: { description: string }) {
  const mounted = useSyncExternalStore(
    subscribe,
    clientSnapshot,
    serverSnapshot,
  );
  const content = useMemo(
    () => (mounted ? renderDescription(description) : description),
    [description, mounted],
  );
  return <div className="place-description preserve">{content}</div>;
}
