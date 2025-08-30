# Streamlit + kubectl image for your app
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# OS deps + curl for kubectl
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates bash git \
 && rm -rf /var/lib/apt/lists/*

# Install kubectl (needed if you want the Deploy button to work inside the container)
RUN set -eux; \
    KVER="$(curl -fsSL https://storage.googleapis.com/kubernetes-release/release/stable.txt)"; \
    curl -fsSLo /usr/local/bin/kubectl \
      "https://storage.googleapis.com/kubernetes-release/release/${KVER}/bin/linux/amd64/kubectl"; \
    chmod +x /usr/local/bin/kubectl

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir streamlit pytest pyyaml

# App code
COPY . .

# Default envs (override in compose / run)
ENV MODEL_NAME=mistral \
    OLLAMA_HOST=http://host.docker.internal:11434 \
    PORT=8501

# Small entrypoint: if a kubeconfig is mounted, rewrite 127.0.0.1 -> host.docker.internal
# so the container can talk to your host-side minikube API server.
RUN printf '%s\n' \
  '#!/bin/sh' \
  'set -e' \
  'if [ -n "$KUBECONFIG" ] && [ -f "$KUBECONFIG" ]; then' \
  '  sed -i "s/127\.0\.0\.1/host.docker.internal/g" "$KUBECONFIG" || true' \
  'fi' \
  'exec "$@"' > /entrypoint.sh && chmod +x /entrypoint.sh

EXPOSE 8501
ENTRYPOINT ["/entrypoint.sh"]
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
