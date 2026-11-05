import { useEffect, useState } from "react";
import {
  ArrowDown,
  ArrowRight,
  Check,
  ChevronRight,
  Clock3,
  ExternalLink,
  MapPin,
  Plane,
  RotateCcw,
  Send,
  ShieldCheck,
  Sparkles,
  Sun,
  TrainFront,
  Users,
  Wallet,
} from "lucide-react";

const examples = [
  "Хочу к тёплому морю в ноябре, с ребёнком и без долгого перелёта",
  "На выходные в красивый город, до 80 000 ₽",
  "Хочу в отпуск, но пока не знаю куда – предложи идеи",
];

const popularTrips = [
  {
    title: "Семейный отдых у моря",
    subtitle: "Тепло, детские активности и короткая дорога",
    prompt: "Хочу к тёплому морю в сентябре, недорого, с ребёнком, без долгих перелётов",
  },
  {
    title: "Выходные в городе",
    subtitle: "Красивые места и поездка на пару дней",
    prompt: "Хочу на выходные в красивый город в ноябре, с прогулками и музеями",
  },
  {
    title: "Спокойный отдых в горах",
    subtitle: "Природа, свежий воздух и уютный отель",
    prompt: "Хочу спокойный отдых в горах на неделю в августе",
  },
  {
    title: "Путешествие на поезде",
    subtitle: "Без перелётов, с комфортной дорогой",
    prompt: "Хочу в Казань в ноябре на поезде, на выходные",
  },
];

const monthNumbers = {
  января: "01",
  февраля: "02",
  марта: "03",
  апреля: "04",
  мая: "05",
  июня: "06",
  июля: "07",
  августа: "08",
  сентября: "09",
  октября: "10",
  ноября: "11",
  декабря: "12",
};

const formatPrice = (value) => new Intl.NumberFormat("ru-RU").format(value);

function getTripEditValues(trip) {
  let dateFrom = trip.dateFrom;
  const dateMatch = trip.dates.match(/(\d{1,2})[–-]\d{1,2}\s+([а-яё]+)\s+(\d{4})/i);
  if (!dateFrom && dateMatch && monthNumbers[dateMatch[2].toLowerCase()]) {
    dateFrom = `${dateMatch[3]}-${monthNumbers[dateMatch[2].toLowerCase()]}-${dateMatch[1].padStart(2, "0")}`;
  }
  const guestMatch = trip.guests.match(/(\d+)\s+взросл\w*(?:\s*·\s*(\d+)\s+реб[её]н\w*)?/i);
  return {
    dateFrom: dateFrom ?? "",
    nights: trip.nights ?? 7,
    adults: trip.adults ?? Number(guestMatch?.[1] ?? 2),
    children: trip.childrenCount ?? Number(guestMatch?.[2] ?? 0),
    budget: trip.budget ?? "",
  };
}

function formatMessageText(text) {
  const lines = text.split(/\r?\n/);
  const inline = (value, keyPrefix) =>
    value.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g).map((part, index) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={`${keyPrefix}-${index}`}>{part.slice(2, -2)}</strong>;
      }
      if (part.startsWith("*") && part.endsWith("*")) {
        return <em key={`${keyPrefix}-${index}`}>{part.slice(1, -1)}</em>;
      }
      return part;
    });

  return lines.map((line, index) => {
    const bullet = line.match(/^\s*[-*•]\s+/);
    return (
      <span className={`message-line ${bullet ? "message-list-line" : ""}`} key={index}>
        {bullet && <span className="message-bullet" aria-hidden="true">•</span>}
        {inline(bullet ? line.slice(bullet[0].length) : line, index)}
        {index < lines.length - 1 && <br />}
      </span>
    );
  });
}

async function requestApi(path, body) {
  const response = await fetch(`/api/agent/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok)
    throw new Error(payload.error ?? "Не удалось выполнить запрос.");
  return payload;
}

function Header({ onReset }) {
  return (
    <header className="topbar">
      <a
        className="brand"
        href="#"
        aria-label="О!дин запрос – на главную"
        onClick={(event) => {
          event.preventDefault();
          onReset();
        }}
      >
        <span className="brand-mark">о!</span>
        <span>один запрос</span>
      </a>
      <nav className="top-nav" aria-label="Основная навигация">
        <a href="#how">Как это работает</a>
        <a href="#plan">Мой план</a>
      </nav>
      <div className="profile">
        <span className="profile-dot">А</span>
        <span>Моё путешествие</span>
      </div>
    </header>
  );
}

function TripResult({ trip, onSelect, onExplore, onBook, onUpdate, bookingLoading, busy }) {
  const [editing, setEditing] = useState(true);
  const [editValues, setEditValues] = useState(() => getTripEditValues(trip));
  useEffect(() => {
    setEditValues(getTripEditValues(trip));
    setEditing(true);
  }, [trip]);
  const selected = trip.hotels.find(
    (hotel) => hotel.id === trip.selectedHotelId,
  );
  const mapPlace = [
    ...new Set(
      [selected?.name, selected?.area, trip.destination.name].filter(Boolean),
    ),
  ].join(", ");
  const mapUrl = `https://yandex.ru/maps/?text=${encodeURIComponent(mapPlace)}`;
  const mapEmbedUrl = new URL("https://yandex.ru/map-widget/v1/");
  mapEmbedUrl.searchParams.set("mode", "search");
  mapEmbedUrl.searchParams.set("text", mapPlace);
  mapEmbedUrl.searchParams.set("z", "12");
  const routeUrl = trip.origin
    ? `https://yandex.ru/maps/?rtext=${encodeURIComponent(`${trip.origin}~${trip.destination.name}`)}`
    : null;
  return (
    <section className="results" id="plan" aria-label="План поездки">
      <div className="result-heading">
        <div>
          <div className="eyebrow">
            <span className="live-dot" /> ВАШ ПЛАН СОБРАН
          </div>
          <h2>
            Похоже, вам понравится <span>{trip.destination.name}</span>
          </h2>
          <p className="destination-reason">{trip.explanation}</p>
        </div>
        <div className="weather-pill">
          <Sun size={18} />
          <span>{trip.weather}</span>
        </div>
      </div>

      <div className="destination-alternatives">
        <div className="alternatives-heading">
          Ещё направления для сравнения
        </div>
        <div className="alternative-list">
          {trip.alternatives.map((alternative) => (
            <article className="alternative-card" key={alternative.id}>
              <div>
                <strong>{alternative.name}</strong>
                <span>
                  {alternative.weather} · {alternative.flightHours} ч в пути
                </span>
              </div>
              <strong className="alternative-price">
                от {formatPrice(alternative.estimate)} ₽
              </strong>
              <button
                type="button"
                onClick={() => onExplore(`Хочу в ${alternative.name}`)}
              >
                Рассмотреть <ArrowRight size={13} />
              </button>
            </article>
          ))}
        </div>
      </div>

      <div className="trip-facts">
        <div>
          <span className="fact-icon">
            <Clock3 size={17} />
          </span>
          <span>
            <small>ДАТЫ</small>
            <strong>{trip.dates}</strong>
          </span>
        </div>
        <div>
          <span className="fact-icon">
            <Users size={17} />
          </span>
          <span>
            <small>КТО ЕДЕТ</small>
            <strong>{trip.guests}</strong>
          </span>
        </div>
        <div>
          <span className="fact-icon">
            <Wallet size={17} />
          </span>
          <span>
            <small>БЮДЖЕТ</small>
            <strong>до {formatPrice(trip.budget)} ₽</strong>
          </span>
        </div>
      </div>
      <div className="trip-edit-heading">
        <div>
          <strong>Подстроить поездку</strong>
          <span>Меняйте даты, состав группы и бюджет</span>
        </div>
        <button
          type="button"
          className="edit-toggle"
          onClick={() => setEditing((value) => !value)}
          aria-expanded={editing}
          aria-controls="trip-edit-form"
        >
          {editing ? "Скрыть настройки" : "Настроить поездку"}
        </button>
      </div>
      {editing && (
        <form
          id="trip-edit-form"
          className="trip-edit-form"
          onSubmit={(event) => {
            event.preventDefault();
            const guests = [
              `${editValues.adults} взрослых`,
              `${editValues.children} детей`,
            ].join(", ");
            onUpdate(
              `Изменить поездку: с ${editValues.dateFrom}, на ${editValues.nights} ночей, ${guests}, бюджет до ${editValues.budget} ₽.`,
            );
            setEditing(false);
          }}
        >
          <label>
            <span>Дата заезда</span>
            <input
              type="date"
              required
              value={editValues.dateFrom}
              onChange={(event) =>
                setEditValues((value) => ({ ...value, dateFrom: event.target.value }))
              }
            />
          </label>
          <label>
            <span>Ночей</span>
            <input
              type="number"
              min="1"
              max="60"
              required
              value={editValues.nights}
              onChange={(event) =>
                setEditValues((value) => ({ ...value, nights: event.target.value }))
              }
            />
          </label>
          <label>
            <span>Взрослых</span>
            <input
              type="number"
              min="1"
              max="9"
              required
              value={editValues.adults}
              onChange={(event) =>
                setEditValues((value) => ({ ...value, adults: event.target.value }))
              }
            />
          </label>
          <label>
            <span>Детей</span>
            <input
              type="number"
              min="0"
              max="9"
              required
              value={editValues.children}
              onChange={(event) =>
                setEditValues((value) => ({ ...value, children: event.target.value }))
              }
            />
          </label>
          <label>
            <span>Бюджет, ₽</span>
            <input
              type="number"
              min="1"
              required
              value={editValues.budget}
              onChange={(event) =>
                setEditValues((value) => ({ ...value, budget: event.target.value }))
              }
            />
          </label>
          <button type="submit" className="edit-submit" disabled={busy}>
            {busy ? "Пересобираю…" : "Обновить поездку"}
          </button>
        </form>
      )}

      <div className="section-title">
        <div>
          <span className="step-number">1</span>
          <div>
            <h3>Как добраться</h3>
            <p>Состыковали дорогу с заселением</p>
          </div>
        </div>
      </div>
      <div className="transport-card">
        <div className="transport-icon">
          <TrainFront size={21} />
        </div>
        <div className="transport-main">
          <strong>{trip.transport.label}</strong>
          <span>Туда и обратно · ориентировочная стоимость</span>
        </div>
        <strong className="transport-price">
          {formatPrice(trip.transport.price)} ₽
        </strong>
      </div>
      <div className="transfer-card">
        <MapPin size={17} />
        <span>{trip.transfer.label}</span>
        <strong>{formatPrice(trip.transfer.price)} ₽</strong>
        <span className="transfer-note">~35 мин</span>
      </div>
      <div className="map-links">
        {routeUrl && (
          <a href={routeUrl} target="_blank" rel="noreferrer">
            Маршрут {trip.origin} – {trip.destination.name}
            <ExternalLink size={14} />
          </a>
        )}
        <a href={mapUrl} target="_blank" rel="noreferrer">
          {selected ? "Отель на Яндекс Картах" : "Направление на Яндекс Картах"}
          <ExternalLink size={14} />
        </a>
      </div>
      <div className="map-embed">
        <iframe
          src={mapEmbedUrl.toString()}
          title={`Яндекс Карты: ${mapPlace}`}
          loading="lazy"
          referrerPolicy="strict-origin-when-cross-origin"
          allowFullScreen
        />
      </div>

      <div className="section-title hotel-title">
        <div>
          <span className="step-number">2</span>
          <div>
            <h3>Где остановиться</h3>
            <p>Подобрал варианты под ваш запрос</p>
          </div>
        </div>
        <span className="option-count">{trip.hotels.length} варианта</span>
      </div>
      <div className="hotel-list">
        {trip.hotels.map((hotel) => {
          const isSelected = selected?.id === hotel.id;
          return (
            <button
              type="button"
              className={`hotel-card ${isSelected ? "selected" : ""}`}
              key={hotel.id}
              onClick={() => onSelect(hotel.id)}
              aria-pressed={isSelected}
            >
              <span className="hotel-picture" aria-hidden="true">
                <span>
                  {trip.destination.id === "sochi"
                    ? "🌊"
                    : trip.destination.id === "antalya"
                      ? "☀️"
                      : "🏛️"}
                </span>
                <i>{hotel.stars} ★</i>
              </span>
              <span className="hotel-info">
                <span className="hotel-name">
                  {hotel.name}
                  {isSelected && (
                    <span className="chosen-mark">
                      <Check size={12} /> ВЫБРАНО
                    </span>
                  )}
                </span>
                <span className="hotel-area">
                  <MapPin size={13} />
                  {hotel.area}
                </span>
                <span className="hotel-feature">{hotel.meal}</span>
                <span
                  className={`cancellation ${hotel.cancellation.includes("Бесплатная") ? "" : "cancellation-warning"}`}
                >
                  <ShieldCheck size={13} />
                  {hotel.cancellation}
                </span>
                <span className="hotel-tradeoff">На заметку: {hotel.risk}</span>
              </span>
              <span className="hotel-price">
                <strong>{formatPrice(hotel.price)} ₽</strong>
                <small>за весь период</small>
                <span>+ дорога</span>
              </span>
            </button>
          );
        })}
      </div>

      <div className="total-card">
        <div className="total-label">
          <span>3</span>
          <div>
            <strong>Всё путешествие</strong>
            <small>Отель + дорога + трансфер</small>
          </div>
        </div>
        <div className="total-amount">
          <strong>{formatPrice(trip.total)} ₽</strong>
          <small>
            {trip.withinBudget
              ? "В пределах вашего бюджета"
              : "Выше бюджета – можно пересобрать"}
          </small>
        </div>
      </div>

      {trip.risk && (
        <div className="risk-note">
          <Sparkles size={16} />
          <span>
            <strong>Честно о выборе.</strong> {trip.risk}
          </span>
        </div>
      )}

      {trip.booking ? (
        <div className="booking-success">
          <span>
            <Check size={19} />
          </span>
          <div>
            <strong>Поездка оформлена – демо</strong>
            <p>
              Номер {trip.booking.confirmationCode}. {trip.booking.notice}
            </p>
          </div>
        </div>
      ) : (
        <div className="checkout-row">
          <div>
            <span className="safe-label">
              <ShieldCheck size={14} />
              {trip.checkoutPending
                ? "Проверьте корзину перед подтверждением"
                : "Можно изменить позже"}
            </span>
            <p>
              {trip.checkoutPending
                ? `В корзине: ${trip.checkoutPending.details}. Итого ${formatPrice(trip.checkoutPending.total)} ₽. Оплата будет имитирована.`
                : "Перед оформлением ещё раз сверим детали."}
            </p>
          </div>
          <button
            type="button"
            className="book-button"
            onClick={onBook}
            disabled={bookingLoading}
          >
            {bookingLoading
              ? "Оформляем…"
              : trip.checkoutPending
                ? "Подтвердить оплату (демо)"
                : "Перейти к оформлению"}{" "}
            <ArrowRight size={17} />
          </button>
        </div>
      )}
      <p className="demo-notice">
        Демо-подбор на синтетических данных. Цены, наличие, погода и транспорт
        не актуальны.
      </p>
    </section>
  );
}

function PopularTrips({ onPick, disabled }) {
  return (
    <aside className="popular-trips" aria-label="Популярные поездки">
      <div className="popular-heading">
        <span className="popular-icon"><Sparkles size={16} /></span>
        <div>
          <h2>Популярные поездки</h2>
          <p>Выберите идею – агент соберёт маршрут</p>
        </div>
      </div>
      <div className="popular-list">
        {popularTrips.map((item, index) => (
          <button
            type="button"
            className="popular-trip"
            key={item.title}
            onClick={() => onPick(item.prompt)}
            disabled={disabled}
          >
            <span className="popular-number">0{index + 1}</span>
            <span className="popular-copy">
              <strong>{item.title}</strong>
              <span>{item.subtitle}</span>
            </span>
            <ChevronRight size={17} />
          </button>
        ))}
      </div>
    </aside>
  );
}

export default function App() {
  const [sessionId, setSessionId] = useState(null);
  const [trip, setTrip] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [bookingLoading, setBookingLoading] = useState(false);
  const [error, setError] = useState("");

  async function sendMessage(text = draft) {
    const message = text.trim();
    if (!message || busy) return;
    setBusy(true);
    setError("");
    setDraft("");
    setMessages((items) => [...items, { role: "user", text: message }]);
    try {
      const result = await requestApi("message", { sessionId, message });
      setSessionId(result.sessionId);
      setTrip(result.trip);
      setMessages((items) => [
        ...items,
        { role: "agent", text: result.reply, choices: result.choices ?? [] },
      ]);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function selectHotel(hotelId) {
    if (!sessionId || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await requestApi("select", { sessionId, hotelId });
      setTrip(result.trip);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function bookTrip() {
    if (!sessionId) return;
    setBookingLoading(true);
    setError("");
    try {
      const result = await requestApi("checkout", { sessionId });
      setTrip(result.trip);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBookingLoading(false);
    }
  }

  function reset() {
    setSessionId(null);
    setTrip(null);
    setMessages([]);
    setDraft("");
    setError("");
  }

  return (
    <div className="app-shell">
      <Header onReset={reset} />
      <main>
        <section className={`hero ${trip ? "hero-compact" : ""}`} id="how">
          <div className="hero-copy">
            <div className="hero-badge">
              <Sparkles size={14} /> ПУТЕШЕСТВИЕ НАЧИНАЕТСЯ С ИДЕИ
            </div>
            <h1>
              Куда хочется?
              <br />
              <span>Остальное устроим.</span>
            </h1>
            <p>
              Расскажите о поездке своими словами – мы подберём направление,
              отель и дорогу в одном плане.
            </p>
          </div>
          <div className="hero-art" aria-hidden="true">
            <div className="sun-disc" />
            <Plane className="plane" size={66} strokeWidth={1.4} />
            <div className="art-label">
              пора
              <br />в путь
            </div>
            <div className="art-cloud cloud-one" />
            <div className="art-cloud cloud-two" />
            <div className="art-cloud cloud-three" />
          </div>
        </section>

        <div className="planner-layout">
        <section className="planner" aria-label="Планирование путешествия">
          <div className="planner-head">
            <div className="avatar">
              <Sparkles size={18} />
            </div>
            <div>
              <strong>Ваш travel агент</strong>
              <span>На связи и уже собирает идеи</span>
            </div>
            {(trip || messages.length > 0) && (
              <button className="reset-button" type="button" onClick={reset}>
                <RotateCcw size={14} /> Новый план
              </button>
            )}
          </div>
          <div className="conversation">
            {messages.length === 0 ? (
              <div className="agent-greeting">
                <span className="greeting-spark">✳</span>
                <div>
                  <strong>Привет! Куда отправимся?</strong>
                  <p>
                    Можно не знать точный город. Расскажите, что важно: море или
                    прогулки, бюджет, кто едет, когда хочется отдохнуть.
                  </p>
                </div>
              </div>
            ) : (
              messages.map((message, index) => (
                <div
                  className={`message ${message.role === "user" ? "user-message" : "agent-message"}`}
                  key={`${message.role}-${index}`}
                >
                  {message.role === "agent" && (
                    <span className="mini-avatar">
                      <Sparkles size={13} />
                    </span>
                  )}
                  <div className="message-content">
                    <p>{formatMessageText(message.text)}</p>
                    {message.role === "agent" && message.choices?.length > 0 && (
                      <div className="destination-choice-list" role="group" aria-label="Выберите направление">
                        {message.choices.map((choice, choiceIndex) => (
                          <button
                            className="destination-choice"
                            type="button"
                            key={choice.id}
                            disabled={busy}
                            onClick={() =>
                              sendMessage(`Выбираю направление «${choice.name}»`)
                            }
                          >
                            <span className="destination-choice-heading">
                              <span>
                                <strong>{choice.name}</strong>
                                <small>{choice.country}</small>
                              </span>
                              {choice.priceFromRub !== null && (
                                <span className="destination-choice-price">
                                  от {formatPrice(choice.priceFromRub)} ₽
                                </span>
                              )}
                            </span>
                            {choice.description && <span className="destination-choice-description">{choice.description}</span>}
                            <span className="destination-choice-facts">
                              {choice.weather && <span><Sun size={14} />{choice.weather}</span>}
                              {choice.travelTime && <span><Clock3 size={14} />{choice.travelTime}</span>}
                            </span>
                            {(choice.pros.length > 0 || choice.cons.length > 0) && (
                              <span className="destination-choice-reason">
                                {choice.pros[0] ?? choice.cons[0]}
                              </span>
                            )}
                            <span className="destination-choice-action">
                              Выбрать направление {choiceIndex + 1} <ChevronRight size={15} />
                            </span>
                          </button>
                        ))}
                        <p className="destination-choice-disclaimer">
                          Цены — синтетические ориентиры каталога, не актуальные тарифы.
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              ))
            )}
            {busy && (
              <div className="thinking">
                <span />
                <span />
                <span /> Собираю варианты
              </div>
            )}
          </div>
          {!trip && messages.length === 0 && (
            <div className="examples">
              {examples.map((example) => (
                <button
                  type="button"
                  key={example}
                  onClick={() => sendMessage(example)}
                >
                  {example}
                  <ChevronRight size={14} />
                </button>
              ))}
            </div>
          )}
          {error && (
            <div className="error-message" role="alert">
              {error}
            </div>
          )}
          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault();
              sendMessage();
            }}
          >
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  sendMessage();
                }
              }}
              placeholder="Например: хочу к морю в ноябре, с ребёнком и до 120 000 ₽"
              rows="1"
              aria-label="Опишите поездку"
            />
            <button
              type="submit"
              disabled={!draft.trim() || busy}
              aria-label="Отправить запрос"
            >
              <Send size={18} />
            </button>
          </form>
          {trip && (
            <p className="replan-hint">
              <ArrowDown size={14} /> Изменились планы? Напишите в поле выше –
              пересоберу поездку с учётом новых условий.
            </p>
          )}
        </section>
        <PopularTrips onPick={(prompt) => sendMessage(prompt)} disabled={busy} />
        </div>

        {trip && (
          <TripResult
            trip={trip}
            onSelect={selectHotel}
            onExplore={(message) => sendMessage(message)}
            onBook={bookTrip}
            onUpdate={(message) => sendMessage(message)}
            bookingLoading={bookingLoading}
            busy={busy}
          />
        )}
        {!trip && (
          <section className="how-it-works">
            <div className="eyebrow">ПРОСТО, КАК РАЗ-ДВА-ТРИ</div>
            <h2>От «хочу куда-нибудь» до «я еду»</h2>
            <div className="steps">
              <div>
                <span>01</span>
                <strong>Расскажите о мечте</strong>
                <p>Без форм и сложных фильтров</p>
              </div>
              <div>
                <span>02</span>
                <strong>Выберите, что по душе</strong>
                <p>Сравните детали и поправьте план</p>
              </div>
              <div>
                <span>03</span>
                <strong>Соберите поездку</strong>
                <p>Отель, дорога и трансфер вместе</p>
              </div>
            </div>
          </section>
        )}
      </main>
      <footer>
        <span className="brand-mark small">о!</span>
        <span>Один запрос – и вы ближе к путешествию.</span>
        <a href="#how">
          Наверх <ArrowDown size={13} />
        </a>
      </footer>
    </div>
  );
}
