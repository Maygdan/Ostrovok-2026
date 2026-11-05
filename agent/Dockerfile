FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

ENV HOST=0.0.0.0
ENV PORT=8000
EXPOSE 8000

CMD ["uv", "run", "--frozen", "odin"]
