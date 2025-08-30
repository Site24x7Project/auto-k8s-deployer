# GenAI‑Powered Kubernetes YAML Generator

![CI](https://github.com/Site24x7Project/auto-k8s-deployer/actions/workflows/ci.yml/badge.svg)

Turns natural‑language app specs into **valid Kubernetes manifests** and lets you **deploy with one click** to Minikube. Built with **Mistral (Ollama) + LangChain + Streamlit** and hardened by deterministic post‑processing and tests.

> *Badge reflects this repo’s default branch (main or otherwise).*

---

## Key Strengths & Impact

* **GenAI → Infra**: Converts messy human prompts (typos, slang) into deployable K8s YAML.
* **Guardrails over guesswork**: Post‑processor enforces names/labels/selectors, tech‑aware images, and HPA v2 metrics; probes come from the template.
* **One‑click deploy**: `kubectl apply` from the UI to your local Minikube cluster.
* **Verified behavior**: 15 manual prompts exercised; **pytest** suite covers critical defaults and HPA logic.

### What this proves (at a glance)

* Deterministic post‑processing makes LLM output **kubectl‑safe**.
* **One‑click Deploy** successfully applies to a real Minikube cluster.
* Guardrails catch common failures (ports, labels/selectors, HPA spec).

---

## Architecture

```
[Streamlit UI]
   → [Prompt Normalizer]
   → [Mistral via Ollama]
   → [YAML Post‑Processor]
   → [kubectl apply]
   → [Minikube]
```

*LLM output is never trusted as‑is; the post‑processor fixes schema, names, images, and HPA metrics before saving/applying.*

---

## Project Structure

```
kube-genai/
├── app.py                 # Streamlit UI (Generate + Deploy)
├── main.py                # CLI generator (no UI)
├── apply_yaml.py          # Simple kubectl apply wrapper
├── prompts/
│   └── kube_template.txt  # LLM prompt template
├── output/
│   └── deployment.yaml    # Last generated YAML
├── tests/
│   └── test_postprocess.py# Minimal, high-signal pytest suite
├── Dockerfile             # Container image for the app UI
├── docker-compose.yml     # One-liner local run (UI + host Ollama/Minikube)
├── requirements.txt
└── README.md
```

---

## Quickstart

### Prerequisites

* **Python 3.10+**
* **Docker Desktop** (or Docker Engine)
* **kubectl** + **Minikube** (tested: Minikube v1.36, K8s v1.33)
* **Ollama** with Mistral model: `ollama pull mistral`

### 1) Create venv & install

```bash
python -m venv venv
# Windows PowerShell
venv\Scripts\Activate.ps1
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 2) Run Ollama (Mistral) in another terminal

```bash
ollama run mistral
```

> If Ollama isn’t on `http://localhost:11434`, set `OLLAMA_HOST` (e.g., `http://127.0.0.1:11434`).

### 3) Start Minikube (for the Deploy button)

```bash
minikube start
kubectl get nodes
```

### 4) Launch the app

```bash
streamlit run app.py
```

### Run with Docker (one‑liner)

```bash
# From repo root (Ollama on host:11434, Minikube running on host)
docker compose up -d
# Open the UI at http://localhost:8501
```

---

## Demo in 60 Seconds

1. In the app, paste this prompt (uses a safe public image):

   ```
   Deploy a flask app with 1 replica on port 80 using image nginxdemos/hello
   ```
2. Click **Generate**, then **Deploy to Kubernetes**.
3. Verify in a terminal:

   ```bash
   kubectl get deploy flask-app
   kubectl get pods -l app=flask-app
   kubectl get svc flask-app-svc
   kubectl port-forward svc/flask-app-svc 8080:80
   # Open http://localhost:8080
   ```

> If you see `ErrImagePull`, the image name/tag is wrong or private—use a public image and Deploy again.

---

## Features

* Prompt normalization (e.g., `pods→replicas`, `flak→flask`, `port fifty→50`).
* **Autoscaling (HPA)** when intent detected; parses min/max + CPU% if specified.
* Sensible defaults (image, replicas, containerPort) with schema clean‑ups.
* Streamlit UI + sample prompts + download.
* Supports Flask / Node.js / Go defaults (image chosen by tech detection).

---

## Sample Prompts

* `Deploy a flask app with 2 replicas on port 8000`
* `Create deployment and service for a Go app on 9000 with autoscaling from 1 to 4 replicas and CPU trigger at 60%`
* `Deploy a flask app with 2 replicas; container runs on 5000 but expose port 80`
* `Deploy a node app on 3000 and enable autoscaling at 75% CPU`
* `start a flak api with 3 pods on port 5050`  *(intentionally misspelled: flak → flask to demonstrate normalization)*

---

## Accuracy & Verification

* **15 manual prompts** exercised normal/typo/default/autoscaling/noise cases.
* **Automated tests (pytest)** — high‑signal checks:

  * Default Service port follows containerPort when not specified.
  * HPA only when autoscale intent; default CPU=60%; parses min/max/% when present.
  * Tech→image defaults (node/go/flask).
  * Fixes `name` outside `metadata`; ensures labels/selectors consistency.
  * Different Service port vs containerPort preserved (expose 80 → target 5000).

Run tests:

```bash
python -m pip install pytest pyyaml
pytest -q
```

---

## Troubleshooting

* **ErrImagePull / ImagePullBackOff**

  * Use a public image (e.g., `nginxdemos/hello`) and click **Deploy** again, or:

    ```bash
    kubectl set image deploy/flask-app flask-app=nginxdemos/hello
    kubectl rollout status deploy/flask-app
    ```
* **No cluster**

  * `minikube start` and confirm `kubectl get nodes` shows `Ready`.
* **Ollama not reachable**

  * Set `OLLAMA_HOST=http://127.0.0.1:11434` before launching Streamlit.

---

## Configuration (env vars)

* `MODEL_NAME` (default: `mistral`)
* `OLLAMA_HOST` (e.g., `http://localhost:11434`)

---

## Known Limitations

* **Negation**: prompts like “do not autoscale” still contain the token `autoscale` and may trigger HPA (keyword intent).
* **Images**: defaults like `sample/app` are placeholders; use a real pullable image for Deploy.

---

## Roadmap (High‑Impact Small Additions)

* **Image/tag preflight**: pull‑check image before apply → fail fast on bad images.
* **Open App button (port‑forward + copy URL)**: run a local port‑forward and show/copy the URL from the UI.
* **Status & Rollback**: rollout status + `kubectl rollout undo` in the UI.

---

## Optional: CI (GitHub Actions)

`.github/workflows/ci.yml`

```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: python -m pip install -U pip
      - run: pip install -r requirements.txt pytest pyyaml
      - run: pytest -q
```

---

## Tech Stack

* Python, Streamlit
* LangChain + Ollama (Mistral)
* Kubernetes, Minikube, `kubectl`
* YAML, Prompt Engineering
* Pytest

---

## Author

**Aswathi Vipin**
[LinkedIn](https://www.linkedin.com/in/aswathivk)

---

## License

MIT — see [LICENSE](LICENSE).
