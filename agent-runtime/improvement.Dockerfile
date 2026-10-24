FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends chromium ffmpeg libreoffice-impress fonts-noto-cjk fonts-liberation git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv
WORKDIR /opt/roami-agent
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN uv pip install --python .venv/bin/python playwright numpy==2.2.6 pandas matplotlib pytest pytest-asyncio
RUN uv pip install --python .venv/bin/python "openpyxl>=3.1,<4"
RUN apt-get update && apt-get install -y --no-install-recommends gcc python3-dev libsndfile1 && rm -rf /var/lib/apt/lists/*
RUN uv pip install --python .venv/bin/python "opencv-python-headless==4.13.0.92" "numpy==2.2.6" "scipy==1.15.3" "numba==0.61.2" "llvmlite==0.44.0" "soundfile==0.13.1" "pesq==0.0.4" "pystoi==0.4.1" "librosa==0.11.0" "onnxruntime==1.22.1"
COPY src ./src
COPY migrations ./migrations
RUN uv sync --frozen --no-dev --inexact
RUN rm -f src/roami_agent/improvement/authored_fixtures.py src/roami_agent/improvement/corpus.py src/roami_agent/improvement/case_specs.json src/roami_agent/improvement/authored_grading.py
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/*
ENV PATH="/opt/roami-agent/.venv/bin:${PATH}" PYTHONUNBUFFERED=1 PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium
ENTRYPOINT ["python", "-m", "roami_agent.improvement.container_agent"]
