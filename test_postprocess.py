import yaml

# Import from your Streamlit app module (app.py at repo root)
from app import _postprocess_yaml, normalize_prompt

def _docs(yaml_str: str):
    return list(yaml.safe_load_all(yaml_str))

# --- Defaults & normalization ---

def test_p2_defaults_service_port_maps_to_container_port():
    # No explicit external port in the prompt: Service.port should follow containerPort
    src = """
apiVersion: apps/v1
kind: Deployment
metadata: {name: flask-app, labels: {app: flask-app}}
spec:
  replicas: 1
  selector: {matchLabels: {app: flask-app}}
  template:
    metadata: {labels: {app: flask-app}}
    spec:
      containers:
      - name: flask-app
        image: sample/app
        ports: [{containerPort: 8080}]
---
apiVersion: v1
kind: Service
metadata: {name: flask-app-svc, labels: {app: flask-app}}
spec:
  selector: {app: flask-app}
  ports: [{port: 80, targetPort: 8080}]
"""
    prompt = "Deploy a Flask app"
    out = _postprocess_yaml(src, normalize_prompt(prompt))
    svc = _docs(out)[1]
    port = svc["spec"]["ports"][0]
    assert port["port"] == 8080 and port["targetPort"] == 8080

def test_normalize_spelled_out_port_to_number():
    norm = normalize_prompt("Deploy a flask app on port fifty")
    assert "port 50" in norm

# --- HPA behavior ---

def test_drop_hpa_when_no_autoscale_intent():
    src = """
apiVersion: apps/v1
kind: Deployment
metadata: {name: flask-app}
spec:
  selector: {matchLabels: {app: flask-app}}
  template:
    metadata: {labels: {app: flask-app}}
    spec:
      containers: [{name: flask-app, image: sample/app}]
---
apiVersion: v1
kind: Service
metadata: {name: flask-app-svc}
spec: {selector: {app: flask-app}, ports: [{port: 80, targetPort: 80}]}
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: {name: should-be-dropped}
spec: {}
"""
    prompt = "Deploy a Flask app"
    out_docs = _docs(_postprocess_yaml(src, normalize_prompt(prompt)))
    kinds = [d["kind"] for d in out_docs]
    assert kinds == ["Deployment", "Service"]

def test_keep_hpa_and_default_cpu_when_autoscale_keyword_present():
    src = """
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: {name: flask-app-hpa}
spec: {}
"""
    prompt = "autoscale a flask app"  # no % given
    out = _postprocess_yaml(src, normalize_prompt(prompt))
    hpa = _docs(out)[0]
    spec = hpa["spec"]
    assert spec["minReplicas"] >= 1
    assert spec["maxReplicas"] >= spec["minReplicas"]
    target = spec["metrics"][0]["resource"]["target"]
    assert target["type"] == "Utilization" and target["averageUtilization"] == 60

def test_hpa_min_max_and_percent_parsed_from_prompt():
    # Values should be inferred from the prompt text
    src = """
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: {name: go-app-hpa}
spec: {}
"""
    prompt = "Create deployment and service for a Go app on 9000 with autoscaling from 1 to 4 replicas and CPU trigger at 60%"
    out = _postprocess_yaml(src, normalize_prompt(prompt))
    hpa = _docs(out)[0]
    spec = hpa["spec"]
    assert spec["minReplicas"] == 1
    assert spec["maxReplicas"] == 4
    target = spec["metrics"][0]["resource"]["target"]
    assert target["type"] == "Utilization" and target["averageUtilization"] == 60

# --- Ports / service mapping ---

def test_service_external_port_differs_from_container_kept():
    # P12: container 5000, expose port 80 → keep as-is
    src = """
apiVersion: apps/v1
kind: Deployment
metadata: {name: flask-app, labels: {app: flask-app}}
spec:
  selector: {matchLabels: {app: flask-app}}
  template:
    metadata: {labels: {app: flask-app}}
    spec:
      containers:
      - name: flask-app
        image: sample/app
        ports: [{containerPort: 5000}]
---
apiVersion: v1
kind: Service
metadata: {name: flask-app-svc, labels: {app: flask-app}}
spec:
  selector: {app: flask-app}
  ports: [{port: 80, targetPort: 5000}]
"""
    prompt = "Deploy a flask app with 2 replicas; container runs on 5000 but expose port 80"
    out = _postprocess_yaml(src, normalize_prompt(prompt))
    svc = _docs(out)[1]
    port = svc["spec"]["ports"][0]
    assert port["port"] == 80 and port["targetPort"] == 5000

# --- Naming / image defaults / metadata hygiene ---

def test_container_name_coerced_to_app_name():
    src = """
apiVersion: apps/v1
kind: Deployment
metadata: {name: flask-app, labels: {app: flask-app}}
spec:
  selector: {matchLabels: {app: flask-app}}
  template:
    metadata: {labels: {app: flask-app}}
    spec:
      containers:
      - name: wrong-name
        image: sample/app
"""
    prompt = "Deploy a Flask app"
    out = _postprocess_yaml(src, normalize_prompt(prompt))
    dep = _docs(out)[0]
    cname = dep["spec"]["template"]["spec"]["containers"][0]["name"]
    assert cname == "flask-app"

def test_image_defaults_follow_tech_detection_node():
    src = """
apiVersion: apps/v1
kind: Deployment
metadata: {labels: {}, name: node-app}
spec:
  selector: {matchLabels: {app: node-app}}
  template:
    metadata: {labels: {app: node-app}}
    spec:
      containers: [{name: node-app, image: ""}]
"""
    prompt = "Deploy a Node.js app"
    out = _postprocess_yaml(src, normalize_prompt(prompt))
    dep = _docs(out)[0]
    image = dep["spec"]["template"]["spec"]["containers"][0]["image"]
    assert image == "sample/nodejs"

def test_fix_metadata_name_when_top_level_name_used():
    src = """
apiVersion: v1
kind: Service
name: flask-app-svc
metadata: {labels: {app: flask-app}}
spec: {selector: {app: flask-app}, ports: [{port: 80, targetPort: 80}]}
"""
    prompt = "Deploy a Flask app"
    out = _postprocess_yaml(src, normalize_prompt(prompt))
    svc = _docs(out)[0]
    assert "name" not in svc
    assert svc["metadata"]["name"] == "flask-app-svc"
