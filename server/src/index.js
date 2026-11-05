import express from "express";
import { ExternalAgentProvider } from "./agent/external-provider.js";
import { createAgentRouter } from "./routes/agent.js";

const app = express();
const port = Number(process.env.PORT ?? 3001);
const provider = new ExternalAgentProvider(
  process.env.AGENT_BASE_URL ?? "http://127.0.0.1:8000",
);

app.use(express.json({ limit: "32kb" }));
app.get("/api/health", async (_request, response) => {
  try {
    const health = await provider.health();
    response.json({ status: "ok", provider: "odin-agent", agent: health.llm });
  } catch (error) {
    response.status(503).json({
      status: "error",
      provider: "odin-agent",
      error: error.message,
    });
  }
});
app.use("/api/agent", createAgentRouter(provider));
app.use((error, _request, response, _next) => {
  console.error(error);
  response.status(error.status ?? 500).json({ error: error.message ?? "Внутренняя ошибка сервера" });
});

app.listen(port, () => {
  console.log(`Travel agent API listening on ${port}`);
  console.log(`Using Odin agent at ${provider.baseUrl}`);
});
