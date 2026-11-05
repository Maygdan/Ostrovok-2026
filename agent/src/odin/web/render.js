// Отрисовка: из состояния сессии строятся реплики, понимание запроса, план, корзина и заказ.

import { el } from "./dom.js";
import { day, duration, plural, rub, sameDay, time } from "./format.js";
import { richText } from "./markdown.js";

const PARTS = [
  ["outbound", "Дорога туда"],
  ["transfer_in", "Трансфер в отель"],
  ["hotel", "Отель"],
  ["transfer_out", "Трансфер из отеля"],
  ["inbound", "Дорога обратно"],
];
const PART_NAMES = Object.fromEntries(PARTS);
const SEVERITY = { error: "Блокирует оформление", warning: "Внимание", info: "К сведению" };
const QUICK_REPLIES = [
  ["На 2 дня позже", "А можно на два дня позже?"],
  ["Бюджет меньше", "Бюджет меньше"],
  ["С нами собака", "С нами будет собака"],
];

// --- чат ---

export function messageBubble(role, text, { steps = [], failed = false } = {}) {
  const bubble = el("div", { class: "message__bubble" }, richText(text));
  const node = el("div", { class: `message message--${role}${failed ? " message--error" : ""}` }, bubble);
  if (steps.length) node.append(stepsList(steps));
  return node;
}

export const typingIndicator = () =>
  el("div", { class: "message message--assistant" },
    el("div", { class: "message__bubble typing", "aria-label": "Агент думает" },
      el("span"), el("span"), el("span")));

function stepsList(steps) {
  const items = steps.map((step) =>
    el("li", { class: step.ok ? "step" : "step step--failed" },
      `${step.ok ? "✓" : "✗"} ${step.tool} — ${step.summary} (${step.duration_ms} мс)`));
  return el("details", { class: "message__steps" },
    el("summary", { text: `Что делал агент (${steps.length})` }),
    el("ul", {}, items));
}

export function renderMode(node, llm) {
  node.hidden = false;
  node.className = llm.is_demo ? "badge" : "badge badge--live";
  node.textContent = llm.is_demo ? "Демо без LLM" : llm.description;
  node.title = llm.is_demo
    ? "LLM_API_KEY не задан: вместо модели работают простые правила. Данные синтетические."
    : "Подключённая модель";
}

// --- понимание запроса ---

export function renderUnderstanding(state) {
  if (!state.transcript.length) return [];
  const facts = state.summary.map((chip) =>
    el("li", { class: "fact" }, el("b", { text: `${chip.label}:` }), chip.value));
  const nodes = [el("h2", { text: "Что я понял" }), el("ul", { class: "facts" }, facts)];
  const { assumptions, notes } = state.request;
  if (assumptions.length) nodes.push(noteList("Допущения — поправьте, если не так", assumptions));
  if (notes.length) nodes.push(noteList("Учитываю", notes));
  return nodes;
}

const noteList = (title, items) =>
  el("div", { class: "notes" }, `${title}:`, el("ul", {}, items.map((item) => el("li", { text: item }))));

// --- план ---

export function renderPlan(state, onQuickReply) {
  const plan = state.plan;
  if (!plan) return [];
  const party = state.summary.find((chip) => chip.label === "Кто едет")?.value ?? "";
  const nights = `${plan.nights} ${plural(plan.nights, "ночь", "ночи", "ночей")}`;
  const nodes = [
    el("div", { class: "plan__head" },
      el("h2", { text: `${plan.destination.name}, ${plan.destination.country}` }),
      el("span", { class: "plan__rev", text: `версия ${plan.revision}` })),
    el("div", { class: "muted", text: `${day(plan.check_in)} – ${day(plan.check_out)} · ${nights} · ${party}` }),
  ];
  if (plan.weather) nodes.push(el("div", { class: "muted", text: weatherLine(plan.weather) }));
  if (state.outdated_parts.length) {
    const names = state.outdated_parts.map((slot) => PART_NAMES[slot].toLowerCase()).join(", ");
    nodes.push(el("div", { class: "alert", text: `Запрос изменился, план ещё не пересобран. Устарело: ${names}.` }));
  }
  for (const [key, label] of PARTS) {
    if (plan[key]) nodes.push(partCard(key, label, plan[key], plan));
  }
  nodes.push(el("div", { class: "total" }, el("span", { text: "Итого" }), el("span", { text: rub(plan.total_price_rub) })));
  nodes.push(issuesList(plan.issues));
  if (!state.order) nodes.push(quickReplies(state, onQuickReply));
  return nodes;
}

function weatherLine(weather) {
  const sea = weather.sea_c == null ? "" : `, вода ${signed(weather.sea_c)}°C`;
  return `Погода: днём ${signed(weather.day_c)}°C, ночью ${signed(weather.night_c)}°C${sea}, дней с осадками: ${weather.rain_days}`;
}

const signed = (value) => (value > 0 ? `+${value}` : `${value}`);

function partCard(key, label, offer, plan) {
  const body = key === "hotel" ? hotelBody(offer)
    : key === "outbound" || key === "inbound" ? transportBody(offer)
    : transferBody(offer);
  const pin = plan.pinned.includes(key) ? [el("span", { class: "tag tag--pin", text: "ваш выбор" })] : [];
  return el("div", { class: `part part--${key}` },
    el("div", { class: "part__top" },
      el("span", { class: "part__label", text: label }),
      el("span", { class: "part__price", text: rub(offer.total_price_rub) })),
    el("div", { class: "part__title", text: offer.title }),
    el("div", { class: "part__meta", text: body.meta }),
    el("div", { class: "tags" }, [...body.tags.map(asTag), ...pin]),
    whyDetails(plan.explanations[key]));
}

const asTag = (text) => el("span", { class: "tag", text });

function transportBody(offer) {
  const nextDay = sameDay(offer.departs_at, offer.arrives_at) ? "" : " (+1 день)";
  const stops = offer.stops
    ? `${offer.stops} ${plural(offer.stops, "пересадка", "пересадки", "пересадок")}`
    : "без пересадок";
  return {
    meta: `${day(offer.departs_at)}, ${time(offer.departs_at)} → ${time(offer.arrives_at)}${nextDay} · ${duration(offer.duration_minutes)} · ${stops}`,
    tags: [
      offer.baggage_included ? "багаж включён" : "без багажа",
      offer.refundable ? "возвратный тариф" : "невозвратный тариф",
      offer.pets_allowed ? "можно с животными" : null,
    ].filter(Boolean),
  };
}

function hotelBody(offer) {
  const hotel = offer.hotel;
  const free = offer.cancellation.free_until;
  return {
    meta: `${hotel.area} · ${offer.nights} ${plural(offer.nights, "ночь", "ночи", "ночей")} · заезд с ${hotel.check_in_from.slice(0, 5)}`,
    tags: [
      free ? `бесплатная отмена до ${day(free)}` : "невозвратный тариф",
      hotel.distance_to_beach_m == null ? null : `до пляжа ${hotel.distance_to_beach_m} м`,
      `до аэропорта ${hotel.distance_to_airport_km} км`,
      hotel.pets_allowed ? "можно с животными" : null,
    ].filter(Boolean),
  };
}

function transferBody(offer) {
  return {
    meta: `подача ${day(offer.pickup_at)}, ${time(offer.pickup_at)} · в пути ${duration(offer.duration_minutes)}`,
    tags: [
      offer.child_seat ? "детское кресло" : null,
      offer.pets_allowed ? "можно с животными" : null,
      offer.meet_and_greet ? "встреча с табличкой" : null,
    ].filter(Boolean),
  };
}

function whyDetails(explanation) {
  if (!explanation) return null;
  const groups = [
    ["pros", "Почему подходит", explanation.pros],
    ["cons", "Чем пожертвовали", explanation.cons],
    ["risks", "Риски", explanation.risks],
  ].filter(([, , items]) => items.length);
  if (!groups.length) return null;
  return el("details", { class: "why" },
    el("summary", { text: "Почему так выбрано" }),
    groups.map(([kind, title, items]) =>
      el("div", { class: `why__group why__group--${kind}` },
        el("b", { text: title }),
        el("ul", {}, items.map((item) => el("li", { text: item }))))));
}

function issuesList(issues) {
  const significant = issues.filter((issue) => issue.severity !== "info");
  const items = issues.map((issue) =>
    el("li", { class: `issue issue--${issue.severity}` },
      el("span", { class: "issue__kind", text: SEVERITY[issue.severity] }), issue.message));
  if (!significant.length) {
    items.unshift(el("li", { class: "issue issue--ok", text: "Стыковки проверены: прилёт, заселение, трансферы и вылет согласованы." }));
  }
  return el("ul", { class: "issues" }, items);
}

function quickReplies(state, onQuickReply) {
  const buttons = QUICK_REPLIES.map(([label, text]) =>
    el("button", { class: "chip", type: "button", text: label, onclick: () => onQuickReply(text) }));
  if (!state.cart) {
    buttons.push(el("button", { class: "btn btn--small", type: "button", text: "Оформить корзину", onclick: () => onQuickReply("Оформляй") }));
  }
  return el("div", { class: "quick" }, buttons);
}

// --- корзина и заказ ---

export function renderCheckout(state, onPay) {
  if (state.order) return orderCard(state.order);
  if (state.cart) return cartCard(state.cart, onPay);
  return [];
}

function cartCard(cart, onPay) {
  const lines = cart.items.map((item) =>
    el("li", {}, el("span", { text: item.title }), el("span", { text: rub(item.price_rub) })));
  return [
    el("h2", { text: "Корзина" }),
    el("ul", { class: "lines" }, lines),
    el("div", { class: "total" }, el("span", { text: "К оплате" }), el("span", { text: rub(cart.total_price_rub) })),
    el("p", { class: "muted", text: "Оплата — имитация, деньги не списываются." }),
    el("button", { class: "btn", type: "button", text: "Оплачиваю (имитация)", onclick: () => onPay("Оплачиваю") }),
  ];
}

function orderCard(order) {
  const lines = order.bookings.map((booking) =>
    el("li", {},
      el("span", { text: `${PART_NAMES[booking.slot]}: ${booking.title}` }),
      el("span", { class: "order__code", text: booking.confirmation_code })));
  return [
    el("h2", { text: `Заказ ${order.id} оформлен` }),
    el("ul", { class: "lines" }, lines),
    el("div", { class: "total" }, el("span", { text: "Оплачено" }), el("span", { text: rub(order.total_price_rub) })),
    el("p", { class: "muted", text: `Платёж ${order.receipt.transaction_id} — имитация, деньги не списывались.` }),
  ];
}
