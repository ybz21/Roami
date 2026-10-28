FROM python:3.12-slim
LABEL org.roami.rsi.shared-daily-policy="3"
RUN apt-get update && apt-get install -y --no-install-recommends chromium ffmpeg libreoffice-impress fonts-noto-cjk fonts-liberation git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv
WORKDIR /opt/roami-agent
COPY pyproject.toml uv.lock ./
COPY case_build.py ./
RUN uv sync --frozen --no-dev --no-install-project
RUN uv pip install --python .venv/bin/python playwright==1.64.1 numpy==2.2.6 pandas matplotlib pytest pytest-asyncio
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers
RUN .venv/bin/python -m playwright install chromium --only-shell \
    && chmod -R a+rX /opt/playwright-browsers \
    && .venv/bin/python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); b.close(); p.stop()"
RUN uv pip install --python .venv/bin/python "openpyxl>=3.1,<4"
RUN apt-get update && apt-get install -y --no-install-recommends gcc python3-dev libsndfile1 && rm -rf /var/lib/apt/lists/*
RUN uv pip install --python .venv/bin/python "opencv-python-headless==4.13.0.92" "numpy==2.2.6" "scipy==1.15.3" "numba==0.61.2" "llvmlite==0.44.0" "soundfile==0.13.1" "pesq==0.0.4" "pystoi==0.4.1" "librosa==0.11.0" "onnxruntime==1.22.1"
COPY src ./src
COPY migrations ./migrations
# Evaluation cases stay on the host, outside the agent image build context.
RUN ROAMI_RSI_CONTAINER_BUILD=1 uv sync --frozen --no-dev --inexact
RUN rm -f src/roami_agent/improvement/evaluation/authored_fixtures.py \
    src/roami_agent/improvement/evaluation/corpus.py \
    src/roami_agent/improvement/evaluation/authored_grading.py
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/*
ENV PATH="/opt/roami-agent/.venv/bin:${PATH}" PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "roami_agent.improvement.container_agent"]
