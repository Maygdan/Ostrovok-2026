// Тонкая обёртка над HTTP API. Ошибки приходят уже с человеческим текстом.

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`/api${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch {
    throw new ApiError("Нет связи с сервером. Проверьте, что он запущен.", 0);
  }
  if (!response.ok) {
    let message = `Ошибка ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = "Сообщение не прошло проверку.";
    } catch {
      // ответ не JSON — остаётся общий текст
    }
    throw new ApiError(message, response.status);
  }
  return response.json();
}

export const createSession = () => request("/sessions", { method: "POST" });
export const getSession = (id) => request(`/sessions/${id}`);
export const sendMessage = (id, text) =>
  request(`/sessions/${id}/messages`, { method: "POST", body: JSON.stringify({ text }) });
