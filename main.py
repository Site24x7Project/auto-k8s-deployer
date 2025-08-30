from langchain.llms import Ollama
from langchain.prompts import PromptTemplate
import os
import re
import yaml

def normalize_prompt(user_prompt: str) -> str:
    # Keep original case, do case-insensitive replacements instead of .lower()
    text = user_prompt
    replacements = {
        "pods": "replicas",
        "pod": "replica",
        "scale up": "scale from 2 to 5 replicas",
        "scale down": "scale from 5 to 2 replicas",
        "start": "deploy",
        "launch": "deploy",
        "hpa": "HorizontalPodAutoscaler",
        "autoscale": "add a HorizontalPodAutoscaler",
        "autoscaling": "add a HorizontalPodAutoscaler",
        "autoscaling from 1 to 4 replicas": "add a HorizontalPodAutoscaler to scale between 1 and 4 replicas",
        "autoscaling from 2 to 5 replicas": "add a HorizontalPodAutoscaler to scale between 2 and 5 replicas",
        "cpu trigger at 60%": "based on 60% CPU usage",
        "trigger at 60% cpu": "based on 60% CPU usage",
        "scaler": "HorizontalPodAutoscaler",
        "flak": "flask",
        "flsk": "flask",
        "ndoe": "node",
        "gonode": "go and node app"
    }
    for wrong, correct in replacements.items():
        text = text.replace(wrong, correct)
        text = text.replace(wrong.capitalize(), correct)  # handle case variants
    return text

def _build_ollama_client():
    """Robustly build Ollama client from env, auto-fixing missing scheme/port."""
    model_name = os.getenv("MODEL_NAME", "mistral")
    ollama_host = os.getenv("OLLAMA_HOST")
    if ollama_host:
        ollama_host = ollama_host.strip()
        if not (ollama_host.startswith("http://") or ollama_host.startswith("https://")):
            if ":" in ollama_host:
                ollama_host = f"http://{ollama_host}"
            else:
                ollama_host = f"http://{ollama_host}:11434"
        return Ollama(model=model_name, base_url=ollama_host)
    return Ollama(model=model_name)

# ---------------- new helpers: tech detection, naming, HPA parsing ----------------

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
        return "sample/app"   # keep your previous default for flask
    return "sample/app"

def _parse_hpa_from_prompt(prompt_text: str):
    """Extract (minReplicas, maxReplicas, cpu%) if present; else None for each."""
    t = (prompt_text or "").lower()
    min_r = max_r = cpu = None

    # between X and Y replicas / from X to Y replicas
    m = re.search(r"(?:between|from)\s+(\d+)\s+(?:and|to)\s+(\d+)\s+replicas", t)
    if m:
        min_r, max_r = int(m.group(1)), int(m.group(2))

    # N% CPU
    p = re.search(r"(\d+)\s*%.*cpu", t)
    if p:
        cpu = int(p.group(1))

    return min_r, max_r, cpu

def _enforce_names_and_labels(doc: dict, app_name: str) -> dict:
    """Make metadata.name, labels, selectors, and container.name consistent with app_name."""
    if not isinstance(doc, dict):
        return doc
    md = doc.setdefault("metadata", {})
    labels = md.setdefault("labels", {})
    labels["app"] = app_name
    kind = doc.get("kind", "")

    # resource names (only fill if missing)
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

# ---------------- existing helpers + small upgrades ----------------

def _has_autoscale_intent(text: str) -> bool:
    t = (text or "").lower()
    return any(x in t for x in ["autoscale", "autoscaling", " hpa", "hpa ", " scale ", "scale to", "scale between"])

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

def _normalize_hpa_v2(doc, min_r=None, max_r=None, cpu_util=None):
    if isinstance(doc, dict) and doc.get("kind") == "HorizontalPodAutoscaler":
        doc["apiVersion"] = "autoscaling/v2"
        spec = doc.setdefault("spec", {})
        # apply parsed values if present
        spec["minReplicas"] = int(min_r) if isinstance(min_r, int) else spec.get("minReplicas", 1)
        default_max = max(3, spec["minReplicas"])
        spec["maxReplicas"] = int(max_r) if isinstance(max_r, int) else spec.get("maxReplicas", default_max)

        # remove legacy field if present
        spec.pop("targetCPUUtilizationPercentage", None)

        # metrics must exist and be a list with Utilization target
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
            # enforce CPU utilization if we parsed it
            if isinstance(metrics, list) and metrics:
                tgt = metrics[0].setdefault("resource", {}).setdefault("target", {})
                if isinstance(cpu_util, int):
                    tgt["type"] = "Utilization"
                    tgt["averageUtilization"] = int(cpu_util)
            spec["metrics"] = metrics
    return doc

# ---- new tiny helpers (ONLY for fixing P2, P12, P14, P15) ----

_VALID_SERVICE_TYPES = {"ClusterIP", "NodePort", "LoadBalancer", "ExternalName"}

def _extract_exposed_port(normalized_prompt: str):
    """Return int port if the prompt explicitly says 'expose port X', else None."""
    t = (normalized_prompt or "").lower()
    m = re.search(r"(?:expose|exposed)\s+port\s+(\d{1,5})", t)
    return int(m.group(1)) if m else None

def _first_container_port(doc):
    try:
        return int(doc["spec"]["template"]["spec"]["containers"][0]["ports"][0]["containerPort"])
    except Exception:
        return None

def _move_stray_resources_into_container(doc):
    """If resources is under spec.template.spec (pod spec), move it into containers[0]."""
    try:
        pod_spec = doc["spec"]["template"]["spec"]
        containers = pod_spec.get("containers", [])
        if not containers:
            return doc
        # if container already has resources, do nothing
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
        # move template-level strategy up if spec.strategy missing
        tpl_spec = spec.get("template", {}).get("spec", {})
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
            # allow common prefix garbage like 'ClusterIPXYZ'
            if tval.startswith("ClusterIP"):
                spec["type"] = "ClusterIP"
            else:
                spec["type"] = "ClusterIP"
    else:
        spec["type"] = "ClusterIP"

    # set ports
    ports = spec.setdefault("ports", [])
    exposed_port = _extract_exposed_port(normalized_prompt)
    if deploy_port is not None:
        if not ports:
            # create default mapping
            ports.append({"port": exposed_port if exposed_port is not None else deploy_port,
                          "targetPort": deploy_port})
        else:
            p0 = ports[0]
            # if no explicit expose, align Service.port with containerPort (fix P2)
            if exposed_port is None:
                if "port" not in p0 or (isinstance(p0.get("port"), int) and p0["port"] == 80):
                    p0["port"] = deploy_port
            # always ensure targetPort present
            if "targetPort" not in p0:
                p0["targetPort"] = deploy_port
    return doc

def _postprocess_yaml(response: str, normalized_prompt: str) -> str:
    """(1) metadata.name placement, (2) tech-based names/labels/container/image,
       (3) only include HPA if intent, (4) HPA bounds/CPU from prompt, (5) v2 metrics list,
       (6) minimal shape repairs for P2, P12, P14, P15 only."""
    docs = list(yaml.safe_load_all(response))
    want_hpa = _has_autoscale_intent(normalized_prompt)
    app_name = _detect_app_name(normalized_prompt)
    min_r, max_r, cpu_util = _parse_hpa_from_prompt(normalized_prompt)

    out = []
    # track containerPort from Deployment to help Service defaults (P2)
    deploy_port_for_app = None

    for d in docs:
        if not isinstance(d, dict):
            continue

        # fix misplaced name
        d = _fix_metadata_name(d)
        # enforce consistent naming/labels/selectors/container name
        d = _enforce_names_and_labels(d, app_name)

        kind = d.get("kind", "")

        if kind == "Deployment":
            # Minimal repairs for malformed shapes (P14, P12/P15)
            d = _move_stray_resources_into_container(d)
            d = _dedupe_and_fix_strategy(d)

            # capture first containerPort for Service defaulting
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

    # Second pass: sanitize Service type and default port to containerPort if no explicit expose (P2, P12)
    for i, d in enumerate(out):
        if isinstance(d, dict) and d.get("kind") == "Service":
            out[i] = _sanitize_service(d, app_name, normalized_prompt, deploy_port_for_app)

    # Re-emit YAML
    return "\n---\n".join(yaml.safe_dump(d, sort_keys=False).rstrip() for d in out)

# -------------------------------------------------------------------

try:
    with open("prompts/kube_template.txt", "r") as file:
        template = file.read()
except Exception as e:
    print(" Error: could not read template:", e)
    exit(1)

user_input = input("Enter app spec (e.g. Deploy a Flask app with 2 replicas on port 5000):\n")

normalized_input = normalize_prompt(user_input)
prompt = PromptTemplate.from_template(template).format(app_spec=normalized_input)

llm = _build_ollama_client()

try:
    response = llm.invoke(prompt)

    # Strip code fences like in app.py
    if "```yaml" in response:
        response = response.split("```yaml", 1)[1].strip()
    if "```" in response:
        response = response.split("```", 1)[0].strip()

    # Clean placeholder tokens
    for token in [
        "<port_number>", "<containerPort>", "<container_port>",
        "<expose_port>", "<exposed_port>", "<your_exposed_port>"
    ]:
        response = response.replace(token, "8080")

    # strict post-processing to match rules
    response = _postprocess_yaml(response, normalized_input)

    # Validate YAML structure
    try:
        list(yaml.safe_load_all(response))
    except Exception as ye:
        print(" YAML validation error:", ye)
        print(" Raw output:\n", response)
        exit(1)

except Exception as e:
    print(" Error generating YAML from LLM:", e)
    response = "# Generation failed. Please rephrase your prompt or try again."

os.makedirs("output", exist_ok=True)
with open("output/deployment.yaml", "w") as f:
    f.write(response)

print("\n✅ YAML saved to output/deployment.yaml")
