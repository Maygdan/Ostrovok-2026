import test from "node:test";
import assert from "node:assert/strict";
import { DemoAgentProvider } from "./demo-provider.js";

test("turns an open-ended family beach request into a complete trip", async () => {
  const provider = new DemoAgentProvider();
  const result = await provider.plan("Тёплое море в ноябре, недорого, с ребёнком, без долгого перелёта");

  assert.equal(result.trip.destination.id, "sochi");
  assert.equal(result.trip.guests, "2 взрослых · 1 ребёнок");
  assert.equal(result.trip.hotels.length, 3);
  assert.equal(result.trip.alternatives.length, 2);
  assert.equal(result.trip.transport.price > 0, true);
  assert.match(result.disclosure, /синтетических данных/);
  assert.match(result.reply, /В ноябре ожидается/);
});

test("rebuilds the existing trip when dates and budget change", async () => {
  const provider = new DemoAgentProvider();
  const initial = await provider.plan("Хочу к морю с ребёнком, бюджет до 120000");
  const revised = await provider.plan("На два дня позже, бюджет до 90000", initial.trip);

  assert.equal(revised.trip.destination.id, initial.trip.destination.id);
  assert.equal(revised.trip.dates, "12–19 ноября 2026");
  assert.equal(revised.trip.budget, 90000);
  assert.equal(revised.trip.hotels.length, 3);
});

test("supports relative changes and preserves the existing destination", async () => {
  const provider = new DemoAgentProvider();
  const initial = await provider.plan("Анталья в декабре, бюджет до 150000");
  const revised = await provider.plan("На два дня позже, бюджет меньше", initial.trip);

  assert.equal(revised.trip.destination.id, "antalya");
  assert.equal(revised.trip.dates, "12–19 декабря 2026");
  assert.equal(revised.trip.budget, 120000);
});
