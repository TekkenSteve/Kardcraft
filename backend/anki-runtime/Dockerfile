FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

COPY requirements.txt ./
ARG ANKI_VERSION=25.9
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache -r requirements.txt "anki==${ANKI_VERSION}"

COPY *.py ./

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8012"]

# FROM python:3.11-slim

# WORKDIR /app

# ENV PYTHONDONTWRITEBYTECODE=1 \
#     PYTHONUNBUFFERED=1 \
#     PIP_DISABLE_PIP_VERSION_CHECK=1

# COPY requirements.txt /app/requirements.txt
# ARG ANKI_VERSION=25.9
# RUN pip install --no-cache-dir -r /app/requirements.txt && \
#     pip install --no-cache-dir "anki==${ANKI_VERSION}"

# COPY *.py /app/

# CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8012"]
