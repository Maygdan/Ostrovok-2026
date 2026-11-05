// Мини-Markdown для ответов модели: заголовки, списки, **жирный**, *курсив*, `код`.
// Всё строится через DOM и textContent: HTML из текста никогда не вставляется.
// Строки остаются строками (пузырь сообщения хранит переносы), поэтому блоки не создаются.

import { el } from "./dom.js";

const INLINE = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)/g;

function inline(text) {
  return text.split(INLINE).map((part) => {
    if (part.length > 4 && part.startsWith("**") && part.endsWith("**")) {
      return el("strong", { text: part.slice(2, -2) });
    }
    if (part.length > 2 && part.startsWith("*") && part.endsWith("*")) {
      return el("em", { text: part.slice(1, -1) });
    }
    if (part.length > 2 && part.startsWith("`") && part.endsWith("`")) {
      return el("code", { text: part.slice(1, -1) });
    }
    return part;
  });
}

function line(text) {
  const heading = text.match(/^#{1,6}\s+(.+)$/);
  if (heading) return [el("strong", { text: heading[1].replaceAll("**", "") })];
  const bullet = text.match(/^(\s*)[-*]\s+(.*)$/);
  return inline(bullet ? `${bullet[1]}• ${bullet[2]}` : text);
}

export const richText = (text) =>
  text.split("\n").flatMap((item, index) => [index ? "\n" : "", ...line(item)]);
