// Контроллер страницы: связывает форму, API и отрисовку.

import * as api from "./api.js";
import { fill } from "./dom.js";
import {
  messageBubble,
  renderCheckout,
  renderMode,
  renderPlan,
  renderUnderstanding,
  typingIndicator,
} from "./render.js";

const SESSION_KEY = "odin.session";
const SUGGESTIONS = [
  "Хочу к тёплому морю в сентябре, недорого, с ребёнком, без долгих перелётов",
  "На выходные в Питер поездом в декабре, вдвоём",
  "Хочу в горы на лыжах в январе с собакой",
];
const WELCOME =
  "Здравствуйте! Опишите поездку одним сообщением своими словами — куда, когда, с кем, " +
  "какой бюджет и что важно. Я уточню только необходимое, подберу направления, отели, " +
  "дорогу и трансферы, проверю стыковки и объясню каждый выбор.";
const DEMO_NOTE =
  "\n\nСейчас работает демо-режим без LLM: я понимаю типовые формулировки (см. примеры ниже). " +
  "Чтобы понимать любые, задайте LLM_API_KEY в .env.";

const $ = (id) => document.getElementById(id);
const ui = {
  messages: $("messages"),
  suggestions: $("suggestions"),
  composer: $("composer"),
  input: $("input"),
  send: $("send"),
  reset: $("reset"),
  mode: $("mode"),
  intro: $("intro"),
  understanding: $("understanding"),
  plan: $("plan"),
  checkout: $("checkout"),
};

let sessionId = null;
let busy = false;

const store = {
  get: () => { try { return localStorage.getItem(SESSION_KEY); } catch { return null; } },
  set: (value) => { try { localStorage.setItem(SESSION_KEY, value); } catch { /* приватный режим */ } },
  clear: () => { try { localStorage.removeItem(SESSION_KEY); } catch { /* приватный режим */ } },
};

function addMessage(node) {
  ui.messages.append(node);
  ui.messages.scrollTop = ui.messages.scrollHeight;
  return node;
}

function applyState(state) {
  renderMode(ui.mode, state.llm);
  ui.intro.hidden = state.transcript.length > 0;
  fill(ui.understanding, renderUnderstanding(state));
  fill(ui.plan, renderPlan(state, send));
  fill(ui.checkout, renderCheckout(state, send));
  fill(ui.suggestions, state.transcript.length ? [] : SUGGESTIONS.map(suggestion));
}

// После ответа показываем ту карточку справа, которая важнее всего сейчас
function revealRelevantCard(state) {
  const card = state.order || state.cart ? ui.checkout : state.plan ? ui.plan : ui.understanding;
  card.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function chip(text, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "chip";
  button.textContent = text;
  button.addEventListener("click", onClick);
  return button;
}

const suggestion = (text) => chip(text, () => send(text));

function setBusy(value) {
  busy = value;
  ui.send.disabled = value;
  ui.input.disabled = value;
  if (!value) ui.input.focus();
}

async function open(state) {
  sessionId = state.session_id;
  store.set(sessionId);
  fill(ui.messages, []);
  if (!state.transcript.length) {
    addMessage(messageBubble("assistant", WELCOME + (state.llm.is_demo ? DEMO_NOTE : "")));
  }
  for (const entry of state.transcript) addMessage(messageBubble(entry.role, entry.text));
  applyState(state);
}

async function startSession() {
  const stored = store.get();
  if (stored) {
    try {
      return await open(await api.getSession(stored));
    } catch (error) {
      if (error.status !== 404) throw error; // временный сбой: сохранённый диалог не трогаем
      store.clear();
    }
  }
  await open(await api.createSession());
}

// Не удалось открыть диалог: пишем причину и даём повторить, а отправку запрещаем,
// чтобы сообщение не ушло в несуществующую сессию и не стёрло сохранённую.
function failToStart(error) {
  ui.input.disabled = true;
  ui.send.disabled = true;
  addMessage(messageBubble("assistant", error.message, { failed: true }));
  fill(ui.suggestions, [chip("Повторить", retryStart)]);
}

function begin() {
  return startSession().catch(failToStart);
}

function retryStart() {
  fill(ui.suggestions, []);
  setBusy(false);
  begin();
}

// После сбоя хода состояние на сервере могло измениться: подтягиваем его в панели
async function resync() {
  try {
    applyState(await api.getSession(sessionId));
  } catch {
    // сервер недоступен — панели остаются как были
  }
}

async function send(text) {
  text = text.trim();
  if (busy || !text || !sessionId) return;
  setBusy(true);
  addMessage(messageBubble("user", text));
  const typing = addMessage(typingIndicator());
  try {
    const reply = await api.sendMessage(sessionId, text);
    typing.remove();
    addMessage(messageBubble("assistant", reply.reply, { steps: reply.steps }));
    applyState(reply.state);
    revealRelevantCard(reply.state);
  } catch (error) {
    typing.remove();
    addMessage(messageBubble("assistant", error.message, { failed: true }));
    if (error.status === 404) store.clear();
    else await resync();
  } finally {
    setBusy(false);
  }
}

async function resetSession() {
  if (busy) return;
  try {
    await open(await api.createSession());
  } catch (error) {
    addMessage(messageBubble("assistant", error.message, { failed: true }));
  }
}

ui.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = ui.input.value;
  ui.input.value = "";
  send(text);
});
ui.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    ui.composer.requestSubmit();
  }
});
ui.reset.addEventListener("click", resetSession);

begin();
