// Форматирование сумм, дат и времени. Время берётся из ISO-строки как есть (местное для пункта),
// без пересчёта в часовой пояс браузера.

const NBSP = String.fromCharCode(160);
const MONTHS = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

export const rub = (amount) =>
  new Intl.NumberFormat("ru-RU").format(amount).replace(/\s/g, NBSP) + NBSP + "₽";

export const day = (iso) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;
export const time = (iso) => iso.slice(11, 16);
export const sameDay = (a, b) => a.slice(0, 10) === b.slice(0, 10);

export function duration(minutes) {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours && rest) return `${hours} ч ${rest} мин`;
  return hours ? `${hours} ч` : `${rest} мин`;
}

export function plural(n, one, few, many) {
  const abs = Math.abs(n);
  if (abs % 100 >= 11 && abs % 100 <= 14) return many;
  if (abs % 10 === 1) return one;
  return abs % 10 >= 2 && abs % 10 <= 4 ? few : many;
}
