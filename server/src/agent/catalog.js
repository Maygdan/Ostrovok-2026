export const destinations = [
  {
    id: "sochi",
    name: "Сочи",
    country: "Россия",
    mood: ["море", "семья", "горы"],
    flightHours: 2.5,
    weather: "около +15 °C",
    transportLabel: "Перелёт · 2 ч 30 мин",
    transportPrice: 18400,
    transferPrice: 1400,
    explanation: "Короткий перелёт, море и инфраструктура для отдыха с ребёнком.",
    hotels: [
      { id: "sochi-sea", name: "Море рядом", stars: 4, area: "Адлер, 8 минут до пляжа", meal: "Завтрак включён", cancellation: "Бесплатная отмена до 3 ноября", price: 42000, tags: ["семья", "море"], risk: "До центра Сочи около 35 минут на электричке." },
      { id: "sochi-garden", name: "Сад у моря", stars: 3, area: "Сириус, тихий район", meal: "Без питания", cancellation: "Без бесплатной отмены", price: 31800, tags: ["семья", "море"], risk: "Питание оплачивается отдельно." },
      { id: "sochi-mountain", name: "Высота", stars: 4, area: "Красная Поляна", meal: "Завтрак включён", cancellation: "Бесплатная отмена до 1 ноября", price: 48900, tags: ["горы"], risk: "До пляжа около 45 минут." }
    ]
  },
  {
    id: "antalya",
    name: "Анталья",
    country: "Турция",
    mood: ["море", "семья", "тепло"],
    flightHours: 5.2,
    weather: "около +22 °C",
    transportLabel: "Перелёт · 5 ч 10 мин",
    transportPrice: 35600,
    transferPrice: 3200,
    explanation: "Самый тёплый вариант у моря: семейные отели и часто включённое питание.",
    hotels: [
      { id: "antalya-family", name: "Лазурный берег", stars: 4, area: "Лара, первая береговая линия", meal: "Завтрак и ужин", cancellation: "Бесплатная отмена до 5 ноября", price: 56800, tags: ["семья", "море"], risk: "Дорога дольше, чем до Сочи." },
      { id: "antalya-park", name: "Парк у моря", stars: 3, area: "Коньяалты, рядом с набережной", meal: "Завтрак включён", cancellation: "Бесплатная отмена до 2 ноября", price: 44300, tags: ["семья", "море"], risk: "Пляж галечный." },
      { id: "antalya-villa", name: "Тихая вилла", stars: 4, area: "Старый город", meal: "Без питания", cancellation: "Без бесплатной отмены", price: 39100, tags: ["город"], risk: "До пляжа нужно ехать." }
    ]
  },
  {
    id: "kaliningrad",
    name: "Калининград",
    country: "Россия",
    mood: ["город", "семья", "прогулки"],
    flightHours: 2.3,
    weather: "около +8 °C",
    transportLabel: "Перелёт · 2 ч 20 мин",
    transportPrice: 16200,
    transferPrice: 1100,
    explanation: "Близко и удобно для короткой поездки, но ноябрь здесь прохладный.",
    hotels: [
      { id: "kaliningrad-center", name: "Дом у острова", stars: 4, area: "Центр, остров Канта", meal: "Завтрак включён", cancellation: "Бесплатная отмена до 5 ноября", price: 36500, tags: ["город"], risk: "Это поездка по городу, не пляжный отдых." },
      { id: "kaliningrad-family", name: "Балтийский двор", stars: 3, area: "Тихий центр", meal: "Завтрак включён", cancellation: "Бесплатная отмена до 3 ноября", price: 28900, tags: ["город", "семья"], risk: "До моря около 40 минут на электричке." },
      { id: "kaliningrad-loft", name: "Кирпичный лофт", stars: 4, area: "Рыбная деревня", meal: "Без питания", cancellation: "Без бесплатной отмены", price: 41200, tags: ["город"], risk: "Вечером в районе может быть шумно." }
    ]
  }
];
