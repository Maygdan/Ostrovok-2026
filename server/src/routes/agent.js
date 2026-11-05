import { Router } from "express";

const sessions = new Map();

export function createAgentRouter(provider) {
  const router = Router();

  router.post("/message", async (request, response, next) => {
    try {
      const { sessionId, message } = request.body ?? {};
      if (typeof message !== "string" || !message.trim()) {
        return response.status(400).json({ error: "Напишите, какую поездку хотите спланировать." });
      }
      if (message.length > 2000) {
        return response.status(400).json({ error: "Сообщение должно быть короче 2000 символов." });
      }
      const session = typeof sessionId === "string" ? sessions.get(sessionId) : undefined;
      if (session?.trip?.stage === "booked") {
        return response.status(409).json({ error: "Поездка уже оформлена. Начните новый план, чтобы подобрать другой вариант." });
      }
      const result = await provider.plan(message.trim(), session?.trip, session?.remoteSessionId);
      const id = sessionId && session
        ? sessionId
        : result.remoteSessionId ?? result.trip?.id;
      if (!id) throw new Error("Провайдер не вернул идентификатор сессии.");
      if (result.trip) result.trip.id = id;
      sessions.set(id, {
        trip: result.trip ?? session?.trip ?? null,
        remoteSessionId: result.remoteSessionId ?? session?.remoteSessionId,
      });
      return response.json({ sessionId: id, ...result });
    } catch (error) {
      return next(error);
    }
  });

  router.post("/select", (request, response) => {
    const { sessionId, hotelId } = request.body ?? {};
    const session = typeof sessionId === "string" ? sessions.get(sessionId) : undefined;
    if (!session) return response.status(404).json({ error: "Сессия поездки не найдена. Начните новый запрос." });
    if (!session.trip) return response.status(400).json({ error: "Сначала выберите направление и соберите план." });
    const hotel = session.trip.hotels.find((item) => item.id === hotelId);
    if (!hotel) return response.status(400).json({ error: "Этот вариант отеля недоступен в текущем плане." });
    if (session.trip.stage === "booked") return response.status(409).json({ error: "Поездка уже оформлена." });
    session.trip.selectedHotelId = hotel.id;
    if (Number.isFinite(hotel.total)) session.trip.total = hotel.total;
    if (typeof hotel.withinBudget === "boolean") session.trip.withinBudget = hotel.withinBudget;
    if (typeof hotel.risk === "string") session.trip.risk = hotel.risk;
    return response.json({ trip: session.trip });
  });

  router.post("/checkout", async (request, response, next) => {
    const { sessionId } = request.body ?? {};
    const session = typeof sessionId === "string" ? sessions.get(sessionId) : undefined;
    if (!session) return response.status(404).json({ error: "Сессия поездки не найдена. Начните новый запрос." });
    if (!session.trip) return response.status(400).json({ error: "Сначала соберите план поездки." });
    if (session.trip.stage === "booked") return response.status(409).json({ error: "Эта поездка уже оформлена." });
    if (session.remoteSessionId) {
      try {
        const message = session.trip.checkoutPending ? "Оплачиваю" : "Оформляй";
        const result = await provider.plan(message, session.trip, session.remoteSessionId);
        if (!result.trip) {
          return response.status(409).json({ error: result.reply ?? "Агент не смог оформить поездку." });
        }
        result.trip.id = sessionId;
        sessions.set(sessionId, {
          trip: result.trip,
          remoteSessionId: result.remoteSessionId,
        });
        return response.json({ trip: result.trip, reply: result.reply });
      } catch (error) {
        return next(error);
      }
    }
    if (!session.trip.selectedHotelId) return response.status(400).json({ error: "Сначала выберите отель." });
    session.trip.stage = "booked";
    session.trip.booking = {
      confirmationCode: `DEMO-${session.trip.id.slice(0, 6).toUpperCase()}`,
      createdAt: new Date().toISOString(),
      notice: "Бронирование имитировано. Оплата и реальные поставщики не подключены."
    };
    return response.json({ trip: session.trip });
  });

  return router;
}
