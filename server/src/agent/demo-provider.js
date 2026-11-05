import { randomUUID } from "node:crypto";
import { destinations } from "./catalog.js";
import { AgentProvider } from "./agent-provider.js";

const defaultDates = "10–17 ноября 2026";

function shiftDates(dates, offset) {
  const match = dates.match(/^(\d{1,2})[–-](\d{1,2})\s+([а-яё]+)\s+(\d{4})$/i);
  if (!match) return dates;
  return `${Number(match[1]) + offset}–${Number(match[2]) + offset} ${match[3]} ${match[4]}`;
}

function parseBudget(text, current) {
  if (current && /бюджет.{0,12}(?:меньше|ниже|уменьш)|дешевле/i.test(text)) {
    return Math.round(current * 0.8);
  }
  const match = text.match(/(?:до|бюджет(?:а)?|лимит)\s*(\d[\d\s]*)\s*(?:₽|руб(?:лей|ля)?|тыс(?:яч)?\s*(?:₽|руб(?:лей|ля)?)?)?/i)
    ?? text.match(/(\d[\d\s]*)\s*(?:₽|руб(?:лей|ля)?)/i);
  if (!match) return current ?? 120000;
  const value = Number(match[1].replace(/\s/g, ""));
  if (!Number.isFinite(value)) return current ?? 120000;
  return /тыс/i.test(match[0]) ? value * 1000 : value;
}

function chooseDestination(text, previous) {
  const normalized = text.toLowerCase();
  const explicit = destinations.find((destination) => normalized.includes(destination.name.toLowerCase()));
  if (explicit) return explicit;
  if (previous && !/куда|направлен|предложи|не знаю|любой|куда-нибудь/i.test(normalized)) {
    return destinations.find((destination) => destination.id === previous.id) ?? destinations[0];
  }

  const wantsBeach = /мор|пляж|куп|тепл|солнеч|ноябр/i.test(normalized);
  const wantsChild = /реб[её]н|семь|дет/i.test(normalized);
  if (wantsBeach && wantsChild) return destinations.find((item) => item.id === "sochi");
  if (wantsBeach) return destinations.find((item) => item.id === "antalya");
  if (/город|архитектур|музе|экскурс/i.test(normalized)) return destinations.find((item) => item.id === "kaliningrad");
  return destinations.find((item) => item.id === "sochi");
}

function makeTrip(text, previous) {
  const destination = chooseDestination(text, previous?.destination);
  const budget = parseBudget(text, previous?.budget);
  const dates = /выходн|на уикенд/i.test(text)
    ? "6–8 ноября 2026"
    : /на два дня позже|на 2 дня позже/i.test(text)
    ? shiftDates(previous?.dates ?? defaultDates, 2)
    : /декабр/i.test(text) ? "10–17 декабря 2026" : previous?.dates ?? defaultDates;
  const guests = /реб[её]н|дет/i.test(text) ? "2 взрослых · 1 ребёнок" : previous?.guests ?? "2 взрослых";
  const dog = /собак|пёс|питом/i.test(text);
  const dogNote = dog ? "Питомец: наличие и условия размещения нужно подтвердить у отеля." : "";
  const sortedHotels = [...destination.hotels].sort((a, b) => {
    const aPenalty = (a.price > budget * 0.6 ? 1 : 0) + (dog && !a.tags.includes("питомцы") ? 1 : 0);
    const bPenalty = (b.price > budget * 0.6 ? 1 : 0) + (dog && !b.tags.includes("питомцы") ? 1 : 0);
    return aPenalty - bPenalty || a.price - b.price;
  });
  const hotels = sortedHotels.map((hotel) => {
    const total = hotel.price + destination.transportPrice + destination.transferPrice;
    return { ...hotel, total, withinBudget: total <= budget };
  });
  const selectedHotelId = hotels.find((hotel) => hotel.withinBudget)?.id ?? hotels[0].id;
  const selected = hotels.find((hotel) => hotel.id === selectedHotelId);
  const total = selected.total;
  const alternatives = destinations
    .filter((item) => item.id !== destination.id)
    .map((item) => {
      const cheapestHotel = [...item.hotels].sort((a, b) => a.price - b.price)[0];
      return {
        id: item.id,
        name: item.name,
        country: item.country,
        weather: item.weather,
        flightHours: item.flightHours,
        transportLabel: item.transportLabel,
        estimate: cheapestHotel.price + item.transportPrice + item.transferPrice,
        explanation: item.explanation
      };
    });

  return {
    id: previous?.id ?? randomUUID(),
    stage: previous?.stage === "booked" ? "booked" : "recommended",
    destination: { id: destination.id, name: destination.name, country: destination.country },
    explanation: destination.explanation,
    dates,
    guests,
    budget,
    weather: destination.weather,
    transport: { label: destination.transportLabel, price: destination.transportPrice },
    transfer: { label: "Индивидуальный трансфер · аэропорт — отель", price: destination.transferPrice },
    hotels,
    alternatives,
    selectedHotelId,
    total,
    withinBudget: total <= budget,
    risk: [selected.risk, dogNote].filter(Boolean).join(" "),
    booking: previous?.booking ?? null
  };
}

function responseText(trip, firstMessage) {
  const price = new Intl.NumberFormat("ru-RU").format(trip.total);
  if (firstMessage) {
    const monthName = trip.dates.split(" ")[1];
    const month = { января: "январе", февраля: "феврале", марта: "марте", апреля: "апреле", мая: "мае", июня: "июне", июля: "июле", августа: "августе", сентября: "сентябре", октября: "октябре", ноября: "ноябре", декабря: "декабре" }[monthName] ?? monthName;
    return `Подобрал ${trip.destination.name}: ${trip.explanation} В ${month} ожидается ${trip.weather}. Составил план на ${trip.dates} для ${trip.guests}. Сумма выбранного варианта — ${price} ₽.`;
  }
  return `Пересобрал поездку: ${trip.destination.name}, ${trip.dates}. Новый ориентир по выбранному варианту — ${price} ₽. Проверьте обновлённые стыковки и условия.`;
}

export class DemoAgentProvider extends AgentProvider {
  async plan(message, previousTrip) {
    const trip = makeTrip(message, previousTrip);
    const firstMessage = !previousTrip;
    return {
      trip,
      reply: responseText(trip, firstMessage),
      disclosure: "Демо-подбор на синтетических данных — цены и наличие не актуальны."
    };
  }
}
