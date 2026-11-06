export function HighlightMatch({ text, query }: { text: string; query: string }) {
  const normalize = (value: string) =>
    value.toLocaleLowerCase("ru").replaceAll("ё", "е");
  const needle = normalize(query.trim());
  if (!needle) return <>{text}</>;
  const haystack = normalize(text);
  const fragments = [];
  let cursor = 0;
  let index = haystack.indexOf(needle);
  while (index !== -1) {
    fragments.push(text.slice(cursor, index));
    fragments.push(
      <mark key={index}>{text.slice(index, index + needle.length)}</mark>,
    );
    cursor = index + needle.length;
    index = haystack.indexOf(needle, cursor);
  }
  fragments.push(text.slice(cursor));
  return <>{fragments}</>;
}
export function descriptionExcerpt(description: string, query: string) {
  const index = description
    .toLocaleLowerCase("ru")
    .replaceAll("ё", "е")
    .indexOf(query.trim().toLocaleLowerCase("ru").replaceAll("ё", "е"));
  const start = Math.max(0, index - 65);
  const end = Math.min(
    description.length,
    Math.max(start + 180, index + query.length + 65),
  );
  return `${start ? "…" : ""}${description.slice(start, end)}${end < description.length ? "…" : ""}`;
}
