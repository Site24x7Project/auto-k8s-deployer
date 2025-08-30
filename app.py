import streamlit as st
import os
import time
from langchain.llms import Ollama
from langchain.prompts import PromptTemplate
import subprocess
import yaml
import re

TEMPLATE_PATH = "prompts/kube_template.txt"
OUTPUT_DIR = "output"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "deployment.yaml")

def normalize_prompt(user_prompt: str) -> str:
    prompt = user_prompt.lower()
    replacements = {
        "pods": "replicas",
        "pod": "replica",
        "scale up": "scale from 2 to 5 replicas",
        "scale down": "scale from 5 to 2 replicas",
        "start": "deploy",
        "launch": "deploy",
        "run": "deploy",
        "create": "deploy",
        "build": "deploy",
        "hpa": "HorizontalPodAutoscaler",
        "autoscale": "add a HorizontalPodAutoscaler",
        "autoscaling": "add a HorizontalPodAutoscaler",
        "scaler": "HorizontalPodAutoscaler",
        "autoscaling from 1 to 4 replicas": "add a HorizontalPodAutoscaler to scale between 1 and 4 replicas",
        "autoscaling from 2 to 5 replicas": "add a HorizontalPodAutoscaler to scale between 2 and 5 replicas",
        "cpu trigger at 60%": "based on 60% CPU usage",
        "trigger at 60% cpu": "based on 60% CPU usage",
        "port fifty": "port 50",
        "fifty": "50",
        "flak": "flask",
        "flsk": "flask",
        "ndoe": "node",
        "gonode": "go and node app"
    }
    for wrong, correct in replacements.items():
        prompt = prompt.replace(wrong, correct)
    return prompt

def _build_ollama_client():
    """Robustly build Ollama client from env, auto-fixing missing scheme/port."""
    model_name = os.getenv("MODEL_NAME", "mistral")
    ollama_host = os.getenv("OLLAMA_HOST")  # may be "localhost", "localhost:11434", etc.
    if ollama_host:
        ollama_host = ollama_host.strip()
        if not (ollama_host.startswith("http://") or ollama_host.startswith("https://")):
            # add scheme and default port if missing
            if ":" in ollama_host:
                ollama_host = f"http://{ollama_host}"
            else:
                ollama_host = f"http://{ollama_host}:11434"
        return Ollama(model=model_name, base_url=ollama_host)
    # fallback to default client (local default)
    return Ollama(model=model_name)

# -------- helpers: intent, naming, image, HPA parsing/normalization --------

def _has_autoscale_intent(text: str) -> bool:
    t = (text or "").lower()
    # include " scale " with spaces to avoid matching "scaler"
    return any(x in t for x in ["autoscale", "autoscaling", " hpa", "hpa ", " scale ", "scale to", "scale between"])

def _detect_app_name(prompt_text: str) -> str:
    t = (prompt_text or "").lower()
    if "node.js" in t or "nodejs" in t or " node " in t:
        return "node-app"
    if " golang" in t or " go " in t or " go-" in t or " go/" in t:
        return "go-app"
    if "flask" in t:
        return "flask-app"
    return "app"

def _map_image_for_app(app_name: str) -> str:
    if app_name.startswith("node"):
        return "sample/nodejs"
    if app_name.startswith("go"):
        return "sample/go"
    if app_name.startswith("flask"):
        return "sample/app"  # keep your default for flask
    return "sample/app"

def _parse_hpa_from_prompt(prompt_text: str):
    """Return (minReplicas, maxReplicas, cpu%) if present; else None for each."""
    t = (prompt_text or "").lower()
    min_r = max_r = cpu = None

    m = re.search(r"(?:between|from)\s+(\d+)\s+(?:and|to)\s+(\d+)\s+replicas", t)
    if m:
        min_r, max_r = int(m.group(1)), int(m.group(2))

    p = re.search(r"(\d+)\s*%.*cpu", t)
    if p:
        cpu = int(p.group(1))

    return min_r, max_r, cpu

def _ensure_image_defaults(doc, app_name: str):
    if isinstance(doc, dict) and doc.get("kind") == "Deployment":
        containers = (doc.get("spec", {}).get("template", {})
                          .get("spec", {}).get("containers", []))
        if containers:
            img = (containers[0].get("image") or "").strip().lower()
            if not img or img in {"sample/flask", "sample"}:
                containers[0]["image"] = _map_image_for_app(app_name)
    return doc

def _fix_metadata_name(doc):
    """Move stray top-level 'name' into metadata.name."""
    if isinstance(doc, dict):
        md = doc.setdefault("metadata", {})
        if "name" not in md and "name" in doc:
            md["name"] = doc.pop("name")
    return doc

def _enforce_names_and_labels(doc: dict, app_name: str) -> dict:
    """Make metadata.name, labels, selectors, and container.name consistent with app_name (only if missing)."""
    if not isinstance(doc, dict):
        return doc
    md = doc.setdefault("metadata", {})
    labels = md.setdefault("labels", {})
    labels["app"] = app_name
    kind = doc.get("kind", "")

    # resource names (fill only if missing)
    if "name" not in md:
        if kind == "Service":
            md["name"] = f"{app_name}-svc"
        elif kind == "HorizontalPodAutoscaler":
            md["name"] = f"{app_name}-hpa"
        else:
            md["name"] = app_name

    # selectors + container name for Deployment
    if kind == "Deployment":
        sel = doc.setdefault("spec", {}).setdefault("selector", {}).setdefault("matchLabels", {})
        sel["app"] = app_name
        pod_lbls = (doc["spec"].setdefault("template", {}).setdefault("metadata", {}).setdefault("labels", {}))
        pod_lbls["app"] = app_name
        containers = (doc["spec"].get("template", {}).get("spec", {}).get("containers", []))
        if containers:
            containers[0]["name"] = app_name

    # selector for Service
    if kind == "Service":
        sel = doc.setdefault("spec", {}).setdefault("selector", {})
        sel["app"] = app_name

    return doc

def _normalize_hpa_v2(doc, min_r=None, max_r=None, cpu_util=None):
    if isinstance(doc, dict) and doc.get("kind") == "HorizontalPodAutoscaler":
        doc["apiVersion"] = "autoscaling/v2"
        spec = doc.setdefault("spec", {})
        # apply parsed values if present; else keep existing/defaults
        spec["minReplicas"] = int(min_r) if isinstance(min_r, int) else spec.get("minReplicas", 1)
        default_max = max(3, spec["minReplicas"])
        spec["maxReplicas"] = int(max_r) if isinstance(max_r, int) else spec.get("maxReplicas", default_max)
        # remove legacy field if present
        spec.pop("targetCPUUtilizationPercentage", None)
        # ensure metrics exists and is a list with Utilization target
        metrics = spec.get("metrics")
        if metrics is None:
            spec["metrics"] = [{
                "type": "Resource",
                "resource": {
                    "name": "cpu",
                    "target": {
                        "type": "Utilization",
                        "averageUtilization": int(cpu_util) if isinstance(cpu_util, int) else 60
                    }
                }
            }]
        else:
            if isinstance(metrics, dict):
                metrics = [metrics]
            if isinstance(metrics, list) and metrics:
                tgt = metrics[0].setdefault("resource", {}).setdefault("target", {})
                if isinstance(cpu_util, int):
                    tgt["type"] = "Utilization"
                    tgt["averageUtilization"] = int(cpu_util)
            spec["metrics"] = metrics
    return doc

# ---- minimal new helpers to fix P2, P12, P14, P15 ONLY ----

_VALID_SERVICE_TYPES = {"ClusterIP", "NodePort", "LoadBalancer", "ExternalName"}

def _extract_exposed_port(normalized_prompt: str):
    """Return int port if prompt explicitly says 'expose port X', else None."""
    t = (normalized_prompt or "").lower()
    m = re.search(r"(?:expose|exposed)\s+port\s+(\d{1,5})", t)
    return int(m.group(1)) if m else None

def _first_container_port(doc):
    try:
        return int(doc["spec"]["template"]["spec"]["containers"][0]["ports"][0]["containerPort"])
    except Exception:
        return None

def _move_stray_resources_into_container(doc):
    """If resources is under spec.template.spec, move it into containers[0] when missing there."""
    try:
        pod_spec = doc["spec"]["template"]["spec"]
        containers = pod_spec.get("containers", [])
        if not containers:
            return doc
        if "resources" in containers[0]:
            return doc
        if "resources" in pod_spec and isinstance(pod_spec["resources"], dict):
            containers[0]["resources"] = pod_spec.pop("resources")
    except Exception:
        pass
    return doc

def _dedupe_and_fix_strategy(doc):
    """Ensure strategy only at Deployment.spec.strategy; drop/move stray ones."""
    try:
        spec = doc.setdefault("spec", {})
        tpl_spec = spec.get("template", {}).get("spec", {})
        # move template-level strategy up if spec.strategy missing
        if "strategy" in tpl_spec and "strategy" not in spec:
            spec["strategy"] = tpl_spec.pop("strategy")
        elif "strategy" in tpl_spec:
            tpl_spec.pop("strategy")
        # move top-level strategy into spec if present
        if "strategy" in doc and "strategy" not in spec:
            spec["strategy"] = doc.pop("strategy")
        elif "strategy" in doc:
            doc.pop("strategy")
    except Exception:
        pass
    return doc

def _sanitize_service(doc, app_name, normalized_prompt, deploy_port):
    """Fix invalid type and default Service.port to containerPort when no explicit expose port is given."""
    if doc.get("kind") != "Service":
        return doc

    spec = doc.setdefault("spec", {})
    # sanitize type
    tval = spec.get("type")
    if isinstance(tval, str):
        if tval not in _VALID_SERVICE_TYPES:
            if tval.startswith("ClusterIP"):
                spec["type"] = "ClusterIP"
            else:
                spec["type"] = "ClusterIP"
    else:
        spec["type"] = "ClusterIP"

    # align ports
    ports = spec.setdefault("ports", [])
    exposed_port = _extract_exposed_port(normalized_prompt)
    if deploy_port is not None:
        if not ports:
            ports.append({"port": exposed_port if exposed_port is not None else deploy_port,
                          "targetPort": deploy_port})
        else:
            p0 = ports[0]
            if exposed_port is None:
                # If user didn't specify external port, mirror containerPort (fixes P2)
                if "port" not in p0 or (isinstance(p0.get("port"), int) and p0["port"] == 80):
                    p0["port"] = deploy_port
            if "targetPort" not in p0:
                p0["targetPort"] = deploy_port
    return doc

def _postprocess_yaml(response: str, normalized_prompt: str) -> str:
    """Enforce: name placement, tech-based names/labels/container/image, HPA only if intent,
       apply parsed HPA bounds/CPU with v2 schema, and minimal shape repairs for P2/P12/P14/P15."""
    docs = list(yaml.safe_load_all(response))
    want_hpa = _has_autoscale_intent(normalized_prompt)
    app_name = _detect_app_name(normalized_prompt)
    min_r, max_r, cpu_util = _parse_hpa_from_prompt(normalized_prompt)

    out = []
    deploy_port_for_app = None  # used to default Service.port when needed

    for d in docs:
        if not isinstance(d, dict):
            continue

        # fix misplaced name
        d = _fix_metadata_name(d)
        # enforce naming/labels/selectors/container name (non-destructive)
        d = _enforce_names_and_labels(d, app_name)

        kind = d.get("kind", "")

        if kind == "Deployment":
            # minimal repairs
            d = _move_stray_resources_into_container(d)   # P12/P15
            d = _dedupe_and_fix_strategy(d)               # P14

            # capture first containerPort for Service defaulting (P2)
            cp = _first_container_port(d)
            if isinstance(cp, int):
                deploy_port_for_app = cp

        if kind == "HorizontalPodAutoscaler":
            if not want_hpa:
                # drop accidental HPA
                continue
            d = _normalize_hpa_v2(d, min_r=min_r, max_r=max_r, cpu_util=cpu_util)

        # tech-appropriate image default
        d = _ensure_image_defaults(d, app_name)

        out.append(d)

    # second pass: sanitize Service type and port mapping (P2/P12)
    for i, d in enumerate(out):
        if isinstance(d, dict) and d.get("kind") == "Service":
            out[i] = _sanitize_service(d, app_name, normalized_prompt, deploy_port_for_app)

    # Re-emit YAML
    return "\n---\n".join(yaml.safe_dump(d, sort_keys=False).rstrip() for d in out)

# -----------------------------------------------------

def generate_yaml(user_prompt: str) -> str:
    # safer template read with friendly error
    try:
        with open(TEMPLATE_PATH, "r") as file:
            template = file.read()
    except Exception as e:
        return f"# Error: could not read template at {TEMPLATE_PATH}: {e}"

    normalized = normalize_prompt(user_prompt)
    formatted_prompt = PromptTemplate.from_template(template).format(app_spec=normalized)

    # robust env handling for OLLAMA_HOST
    llm = _build_ollama_client()

    try:
        response = llm.invoke(formatted_prompt)

        # Clean triple backtick markdown
        if "```yaml" in response:
            response = response.split("```yaml", 1)[1].strip()
        if "```" in response:
            response = response.split("```", 1)[0].strip()

        # Fix any placeholder tokens from LLM (fallback cleanup)
        for token in [
            "<port_number>", "<containerPort>", "<container_port>",
            "<expose_port>", "<exposed_port>", "<your_exposed_port>"
        ]:
            response = response.replace(token, "8080")

        # strict post-processing to match your rules
        response = _postprocess_yaml(response, normalized)

        # YAML validation before save/apply
        try:
            list(yaml.safe_load_all(response))
        except Exception as ye:
            return f"# YAML validation error: {ye}\n# Raw output below:\n{response}"

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(OUTPUT_FILE, "w") as f:
            f.write(response)
        return response
    except Exception as e:
        return f"# Error generating YAML: {str(e)}"

# ----------- STREAMLIT UI ------------------
st.set_page_config(page_title="K8s YAML GenAI", layout="centered")
st.title("Kubernetes YAML Generator (with Mistral GenAI)")

st.markdown("Enter a natural language prompt like:")
st.code("start a flak api with 3 pods on port 5050")
st.code("autoscale a ndoejs app to scale up on port 3035")

sample_prompts = [
    "Deploy a flask app with 2 replicas on port 8000",
    "start a flak api with 3 pods on port 5050",
    "autoscale a ndoejs app to scale up on port 3035",
    "Create deployment and service for a Go app on 9000 with autoscaling from 1 to 4 replicas and CPU trigger at 60%",
]

selected_prompt = st.selectbox("Try a sample prompt:", [""] + sample_prompts)

user_input = st.text_area("Or write your own prompt:", value=selected_prompt if selected_prompt else "", height=100)

if st.button("Generate YAML"):
    with st.spinner("Generating Kubernetes YAML..."):
        start_time = time.time()
        result = generate_yaml(user_input)
        elapsed = time.time() - start_time

    st.success(f"YAML generated in {elapsed:.2f} seconds")
    st.code(result, language="yaml")

if os.path.exists(OUTPUT_FILE):
    with open(OUTPUT_FILE, "rb") as file:
        st.download_button("⬇Download deployment.yaml", file, file_name="deployment.yaml", mime="text/yaml")

st.markdown("---")

if st.button("Deploy to Kubernetes"):
    try:
        result = subprocess.run(
            ["kubectl", "apply", "-f", OUTPUT_FILE],
            capture_output=True,
            text=True,
            timeout=60  # avoids hanging forever
        )
        if result.returncode == 0:
            st.success("YAML successfully applied to your cluster!")
            st.code(result.stdout)
        else:
            st.error(" Failed to apply YAML. See error below:")
            st.code(result.stderr or result.stdout)
    except subprocess.TimeoutExpired:
        st.error(" kubectl apply timed out. Is your cluster reachable?")
    except Exception as e:
        st.error(f" Error running kubectl: {str(e)}")
