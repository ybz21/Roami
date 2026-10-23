FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends chromium ffmpeg libreoffice-impress fonts-noto-cjk fonts-liberation git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv
WORKDIR /opt/roami-agent
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN uv pip install --python .venv/bin/python playwright numpy pandas matplotlib pytest pytest-asyncio
COPY src ./src
COPY migrations ./migrations
RUN uv sync --frozen --no-dev --inexact
RUN rm -f src/roami_agent/improvement/authored_fixtures.py src/roami_agent/improvement/corpus.py src/roami_agent/improvement/case_specs.json src/roami_agent/improvement/authored_grading.py
ENV PATH="/opt/roami-agent/.venv/bin:${PATH}" PYTHONUNBUFFERED=1 PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium
ENTRYPOINT ["python", "-m", "roami_agent.improvement.container_agent"]
