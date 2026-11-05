import test from "node:test";
import assert from "node:assert/strict";
import { ExternalAgentProvider } from "./external-provider.js";

const originalFetch = global.fetch;

function agentState(plan) {
  return {
    session_id: "agent-session",
    llm: { description: "demo", is_demo: true },
    summary: [{ label: "Откуда", value: "Москва" }],
    plan,
    cart: null,
    order: null,
  };
}

function mockFetch(state, steps = []) {
  return async (url, options = {}) => {
    const requestUrl = String(url);
    if (requestUrl.endsWith("/api/sessions")) {
      return new Response(JSON.stringify({ session_id: "agent-session" }), {
        headers: { "content-type": "application/json" },
      });
    }
    if (requestUrl.endsWith("/api/sessions/agent-session/messages")) {
      return new Response(
        JSON.stringify({ reply: "Ответ агента", steps, state }),
        { headers: { "content-type": "application/json" } },
      );
    }
    throw new Error(`Unexpected request: ${requestUrl} ${options.method ?? "GET"}`);
  };
}

test("maps the integrated agent state to the app trip format", async () => {
  global.fetch = mockFetch(
    agentState({
      destination: {
        id: "sochi",
        name: "Сочи",
        country: "Россия",
        description: "Короткий перелёт и море для семейного отдыха.",
      },
      check_in: "2026-11-10",
      check_out: "2026-11-17",
      built_for: {
        party: { adults: 2, children_ages: [7], pets: [] },
        budget_total_rub: 120000,
      },
      total_price_rub: 118800,
      issues: [{ message: "Всё в пределах бюджета." }],
      hotel: {
        id: "sochi-family:rate-1",
        hotel: {
          name: "Семейный берег",
          stars: 4,
          area: "Адлер",
          tags: ["семья", "море"],
        },
        meal_plan: "BB",
        total_price_rub: 80000,
        cancellation: { refundable: true, free_until: "2026-11-05" },
      },
      outbound: { title: "Рейс туда", total_price_rub: 18000 },
      inbound: { title: "Рейс обратно", total_price_rub: 18000 },
      transfer_in: { title: "Трансфер в отель", total_price_rub: 1400 },
      transfer_out: { title: "Трансфер в аэропорт", total_price_rub: 1400 },
      weather: { day_c: 15, night_c: 8, sea_c: 18, rain_days: 5 },
    }),
  );
  const provider = new ExternalAgentProvider("http://agent:8000");
  const result = await provider.plan("Хочу к морю", null);

  assert.equal(result.remoteSessionId, "agent-session");
  assert.equal(result.trip.destination.id, "sochi");
  assert.equal(result.trip.origin, "Москва");
  assert.equal(result.trip.dates, "10–17 ноября 2026");
  assert.equal(result.trip.guests, "2 взрослых · 1 ребёнок");
  assert.equal(result.trip.transport.price, 36000);
  assert.equal(result.trip.transfer.price, 2800);
  assert.equal(result.trip.total, 118800);
  assert.equal(result.trip.hotels[0].name, "Семейный берег");
  assert.equal(result.trip.hotels[0].meal, "Завтрак включён");
  assert.equal(result.trip.checkoutPending, null);
  assert.match(result.reply, /Ответ агента/);
  assert.match(result.disclosure, /Демо-режим/);
});

test("keeps agent sessions alive when it asks the user to choose a destination", async () => {
  global.fetch = mockFetch(agentState(null));
  const provider = new ExternalAgentProvider("http://agent:8000");
  const result = await provider.plan("Хочу отпуск в сентябре", null);

  assert.equal(result.trip, null);
  assert.equal(result.remoteSessionId, "agent-session");
});

test("passes structured destination choices to the client without leaking tool internals", async () => {
  global.fetch = mockFetch(agentState(null), [
    {
      tool: "search_destinations",
      ok: true,
      choices: [
        {
          id: "sochi",
          name: "Сочи",
          country: "Россия",
          description: "Море и короткая дорога.",
          price_from_rub: 48000,
          travel_time: "2 ч 30 мин",
          weather: "+22 °C",
          pros: ["Тёплое море", "Короткий перелёт"],
          cons: ["Высокий сезон"],
          score: 0.9,
        },
        { id: "invalid", name: "Без страны" },
      ],
    },
  ]);
  const provider = new ExternalAgentProvider("http://agent:8000");

  const result = await provider.plan("Хочу к морю", null);

  assert.deepEqual(result.choices, [
    {
      id: "sochi",
      name: "Сочи",
      country: "Россия",
      description: "Море и короткая дорога.",
      priceFromRub: 48000,
      travelTime: "2 ч 30 мин",
      weather: "+22 °C",
      pros: ["Тёплое море", "Короткий перелёт"],
      cons: ["Высокий сезон"],
    },
  ]);
});

test("reports errors instead of silently switching to the local demo provider", async () => {
  global.fetch = async () => new Response(
    JSON.stringify({ detail: "LLM is unavailable" }),
    { status: 502, headers: { "content-type": "application/json" } },
  );
  const provider = new ExternalAgentProvider("http://agent:8000");

  await assert.rejects(provider.plan("Хочу к морю", null), {
    message: "LLM is unavailable",
    status: 502,
  });
});

test.after(() => {
  global.fetch = originalFetch;
});
