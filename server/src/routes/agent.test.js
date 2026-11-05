import test from "node:test";
import assert from "node:assert/strict";
import express from "express";
import { createAgentRouter } from "./agent.js";
import { DemoAgentProvider } from "../agent/demo-provider.js";

test("supports a complete demo planning and booking flow", async (context) => {
  const app = express();
  app.use(express.json());
  app.use("/api/agent", createAgentRouter(new DemoAgentProvider()));
  const server = app.listen(0);
  context.after(() => new Promise((resolve) => server.close(resolve)));
  await new Promise((resolve) => server.once("listening", resolve));
  const baseUrl = `http://127.0.0.1:${server.address().port}/api/agent`;

  const planResponse = await fetch(`${baseUrl}/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: "Тёплое море с ребёнком, до 120000 ₽" })
  });
  assert.equal(planResponse.status, 200);
  const plan = await planResponse.json();
  const hotelId = plan.trip.hotels[1].id;

  const selectionResponse = await fetch(`${baseUrl}/select`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessionId: plan.sessionId, hotelId })
  });
  assert.equal(selectionResponse.status, 200);
  assert.equal((await selectionResponse.json()).trip.selectedHotelId, hotelId);

  const checkoutResponse = await fetch(`${baseUrl}/checkout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessionId: plan.sessionId })
  });
  assert.equal(checkoutResponse.status, 200);
  const bookedTrip = (await checkoutResponse.json()).trip;
  assert.equal(bookedTrip.stage, "booked");
  assert.match(bookedTrip.booking.confirmationCode, /^DEMO-/);

  const reviseResponse = await fetch(`${baseUrl}/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessionId: plan.sessionId, message: "Хочу другие даты" })
  });
  assert.equal(reviseResponse.status, 409);
});

test("keeps an agent session through destination selection and confirmed checkout", async (context) => {
  const messages = [];
  const provider = {
    async plan(message, previousTrip, remoteSessionId) {
      messages.push({ message, remoteSessionId });
      if (message === "первый вариант") {
        return {
          trip: {
            id: "agent-session",
            stage: "recommended",
            hotels: [{ id: "hotel-1" }],
            selectedHotelId: "hotel-1",
            checkoutPending: null,
          },
          remoteSessionId: "agent-session",
          reply: "План готов",
        };
      }
      if (message === "Оформляй") {
        return {
          trip: { ...previousTrip, checkoutPending: { total: 10000, items: 1 } },
          remoteSessionId,
          reply: "Проверьте корзину",
        };
      }
      if (message === "Оплачиваю") {
        return {
          trip: { ...previousTrip, stage: "booked", checkoutPending: null },
          remoteSessionId,
          reply: "Оформлено",
        };
      }
      return {
        trip: null,
        remoteSessionId: "agent-session",
        reply: "Выберите направление",
      };
    },
  };
  const app = express();
  app.use(express.json());
  app.use("/api/agent", createAgentRouter(provider));
  const server = app.listen(0);
  context.after(() => new Promise((resolve) => server.close(resolve)));
  await new Promise((resolve) => server.once("listening", resolve));
  const baseUrl = `http://127.0.0.1:${server.address().port}/api/agent`;
  const post = (path, body) =>
    fetch(`${baseUrl}/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

  const initial = await post("message", { message: "Хочу в отпуск" });
  const initialResult = await initial.json();
  assert.equal(initialResult.trip, null);
  assert.equal(initialResult.sessionId, "agent-session");

  const selected = await post("message", {
    sessionId: initialResult.sessionId,
    message: "первый вариант",
  });
  assert.equal((await selected.json()).trip.selectedHotelId, "hotel-1");

  const cartResponse = await post("checkout", { sessionId: initialResult.sessionId });
  assert.deepEqual((await cartResponse.json()).trip.checkoutPending, { total: 10000, items: 1 });
  const paidResponse = await post("checkout", { sessionId: initialResult.sessionId });
  assert.equal((await paidResponse.json()).trip.stage, "booked");
  assert.deepEqual(
    messages.map(({ message }) => message),
    ["Хочу в отпуск", "первый вариант", "Оформляй", "Оплачиваю"],
  );
  assert.ok(
    messages.slice(1).every(({ remoteSessionId }) => remoteSessionId === "agent-session"),
  );
});
