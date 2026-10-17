FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install . && rm -rf src

COPY suites ./suites
COPY demo ./demo
# live mode: the example agent (stdlib only) and the entrypoint that starts it when configured
COPY examples/ollama_agent.py ./examples/
COPY deploy/start.sh ./deploy/

USER nobody
# PORT is overridden by the platform (Render sets 10000, DigitalOcean sets http_port)
ENV HOST=0.0.0.0 PORT=8080
EXPOSE 8080
CMD ["sh", "deploy/start.sh"]
