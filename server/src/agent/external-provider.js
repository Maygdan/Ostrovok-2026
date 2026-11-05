import { AgentProvider } from "./agent-provider.js";

const monthNames = [
  "января",
  "февраля",
  "марта",
  "апреля",
  "мая",
  "июня",
  "июля",
  "августа",
  "сентября",
  "октября",
  "ноября",
  "декабря",
];

const mealNames = {
  RO: "Без питания",
  BB: "Завтрак включён",
  HB: "Завтрак и ужин",
  FB: "Полный пансион",
  AI: "Всё включено",
};

function formatDates(checkIn, checkOut) {
  if (!checkIn || !checkOut) return "—";
  const start = new Date(`${checkIn}T12:00:00`);
  const end = new Date(`${checkOut}T12:00:00`);
  return `${start.getDate()}–${end.getDate()} ${monthNames[start.getMonth()]} ${start.getFullYear()}`;
}

function formatGuests(party) {
  if (!party) return "2 взрослых";
  const adults = Number(party.adults ?? 2);
  const children = Array.isArray(party.children_ages) ? party.children_ages.length : 0;
  const pets = Array.isArray(party.pets) ? party.pets.length : 0;
  const guests = [`${adults} взрослых`];
  if (children) guests.push(`${children} ${children === 1 ? "ребёнок" : "детей"}`);
  if (pets) guests.push(`${pets} питомец`);
  return guests.join(" · ");
}

function formatWeather(weather) {
  if (!weather) return "Погода по сезону";
  const temperature = (value) => `${value > 0 ? "+" : ""}${value} °C`;
  const details = [`днём ${temperature(weather.day_c)}`, `ночью ${temperature(weather.night_c)}`];
  if (weather.sea_c !== null && weather.sea_c !== undefined) {
    details.push(`вода ${temperature(weather.sea_c)}`);
  }
  if (weather.rain_days !== undefined) details.push(`осадки ${weather.rain_days} дн.`);
  return details.join(", ");
}

function formatRisk(plan) {
  return (plan.issues ?? []).map((issue) => issue.message).filter(Boolean).join(" ");
}

function normalizeTrip(plan, state, previousTrip) {
  const hotel = plan.hotel;
  const outbound = plan.outbound;
  const inbound = plan.inbound;
  const transfers = [plan.transfer_in, plan.transfer_out].filter(Boolean);
  const transportPrice =
    Number(outbound?.total_price_rub ?? 0) + Number(inbound?.total_price_rub ?? 0);
  const transferPrice = transfers.reduce(
    (total, transfer) => total + Number(transfer.total_price_rub ?? 0),
    0,
  );
  const total = Number(plan.total_price_rub ?? 0);
  const budget = Number(plan.built_for?.budget_total_rub ?? previousTrip?.budget ?? total);
  const risk = formatRisk(plan);
  const order = state.order;
  const cart = state.cart;

  return {
    id: previousTrip?.id,
    stage: order ? "booked" : "recommended",
    origin: state.summary?.find((item) => item.label === "Откуда")?.value ?? null,
    destination: {
      id: plan.destination.id,
      name: plan.destination.name,
      country: plan.destination.country,
    },
    explanation: plan.destination.description ?? "",
    dates: formatDates(plan.check_in, plan.check_out),
    dateFrom: plan.check_in,
    nights: Number(plan.nights ?? 7),
    guests: formatGuests(plan.built_for?.party),
    adults: Number(plan.built_for?.party?.adults ?? 2),
    childrenCount: plan.built_for?.party?.children_ages?.length ?? 0,
    budget,
    weather: formatWeather(plan.weather),
    transport: {
      label: [outbound?.title, inbound?.title].filter(Boolean).join(" · ") || "Транспорт",
      price: transportPrice,
    },
    transfer: {
      label: transfers.map((transfer) => transfer.title).filter(Boolean).join(" · ") || "Трансфер",
      price: transferPrice,
    },
    hotels: hotel
      ? [
          {
            id: hotel.id,
            name: hotel.hotel?.name ?? hotel.name ?? "Отель",
            stars: Number(hotel.hotel?.stars ?? hotel.stars ?? 0),
            area: hotel.hotel?.area ?? hotel.area ?? "",
            meal: mealNames[hotel.meal_plan] ?? hotel.meal ?? "Питание по тарифу",
            cancellation: hotel.cancellation?.refundable
              ? `Бесплатная отмена до ${hotel.cancellation.free_until ?? "даты заезда"}`
              : "Без бесплатной отмены",
            price: Number(hotel.total_price_rub ?? 0),
            tags: hotel.hotel?.tags ?? hotel.hotel?.amenities ?? [],
            risk,
          },
        ]
      : [],
    alternatives: [],
    selectedHotelId: hotel?.id ?? null,
    total,
    withinBudget: total <= budget,
    risk,
    checkoutPending: cart
      ? {
          total: Number(cart.total_price_rub ?? total),
          items: cart.items?.length ?? 0,
          details: (cart.items ?? [])
            .map((item) => `${item.title}: ${Number(item.price_rub).toLocaleString("ru-RU")} ₽`)
            .join("; "),
        }
      : null,
    booking: order
      ? {
          confirmationCode: order.bookings?.[0]?.confirmation_code ?? order.id,
          createdAt: order.payment?.paid_at ?? "",
          notice: "Оплата и бронирование имитируются: реальные деньги не списываются.",
        }
      : null,
  };
}

function normalizeChoices(steps) {
  const search = Array.isArray(steps)
    ? steps.find(
        (step) =>
          step?.tool === "search_destinations" &&
          step.ok === true &&
          Array.isArray(step.choices),
      )
    : null;
  if (!search) return [];

  return search.choices
    .filter(
      (choice) =>
        typeof choice?.id === "string" &&
        typeof choice.name === "string" &&
        typeof choice.country === "string",
    )
    .map((choice) => ({
      id: choice.id,
      name: choice.name,
      country: choice.country,
      description: typeof choice.description === "string" ? choice.description : "",
      priceFromRub: Number.isFinite(choice.price_from_rub) ? choice.price_from_rub : null,
      travelTime: typeof choice.travel_time === "string" ? choice.travel_time : "",
      weather: typeof choice.weather === "string" ? choice.weather : "",
      pros: Array.isArray(choice.pros)
        ? choice.pros.filter((item) => typeof item === "string").slice(0, 2)
        : [],
      cons: Array.isArray(choice.cons)
        ? choice.cons.filter((item) => typeof item === "string").slice(0, 1)
        : [],
    }));
}

export class ExternalAgentProvider extends AgentProvider {
  constructor(baseUrl = process.env.AGENT_BASE_URL ?? "http://127.0.0.1:8000") {
    super();
    this.baseUrl = baseUrl.replace(/\/+$/, "");
  }

  async requestJson(path, options = {}) {
    const response = await fetch(`${this.baseUrl}${path}`, {
      headers: { "Content-Type": "application/json", ...(options.headers ?? {}) },
      ...options,
    });
    const contentType = response.headers.get("content-type") ?? "";
    const body = contentType.includes("application/json")
      ? await response.json()
      : await response.text();

    if (!response.ok) {
      const message =
        typeof body === "string"
          ? body
          : body?.detail ?? "Не удалось получить ответ от travel-агента.";
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return body;
  }

  async health() {
    return this.requestJson("/api/health");
  }

  async plan(message, previousTrip, remoteSessionId) {
    const session = remoteSessionId
      ? { session_id: remoteSessionId }
      : await this.requestJson("/api/sessions", { method: "POST" });
    const sessionId = session.session_id;
    if (typeof sessionId !== "string" || !sessionId) {
      throw new Error("Travel-агент не вернул идентификатор сессии.");
    }

    const result = await this.requestJson(`/api/sessions/${sessionId}/messages`, {
      method: "POST",
      body: JSON.stringify({ text: message }),
    });
    const state = result.state;
    if (!state) throw new Error("Travel-агент вернул ответ без состояния сессии.");

    return {
      trip: state.plan ? normalizeTrip(state.plan, state, previousTrip) : null,
      remoteSessionId: sessionId,
      reply: result.reply,
      choices: normalizeChoices(result.steps),
      disclosure: state.llm?.is_demo
        ? "Демо-режим агента: используются синтетические данные, модель ИИ не подключена."
        : "Подбор на синтетических данных. Реальные цены и наличие не подключены.",
    };
  }
}
