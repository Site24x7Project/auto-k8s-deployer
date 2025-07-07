import streamlit as st
import os
import time
from langchain.llms import Ollama
from langchain.prompts import PromptTemplate
import subprocess
import yaml

# --------------- CONFIG --------------------
TEMPLATE_PATH = "prompts/kube_template.txt"
OUTPUT_DIR = "output"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "deployment.yaml")

# ------------- PROMPT NORMALIZATION ---------
def normalize_prompt(user_prompt: str) -> str:
    prompt = user_prompt.lower()
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
        "scaler": "HorizontalPodAutoscaler",
        "autoscaling from 1 to 4 replicas": "add a HorizontalPodAutoscaler to scale between 1 and 4 replicas",
        "autoscaling from 2 to 5 replicas": "add a HorizontalPodAutoscaler to scale between 2 and 5 replicas",
        "cpu trigger at 60%": "based on 60% CPU usage",
        "trigger at 60% cpu": "based on 60% CPU usage",
        "flak": "flask",
        "flsk": "flask",
        "ndoe": "node",
        "gonode": "go and node app"
    }
    for wrong, correct in replacements.items():
        prompt = prompt.replace(wrong, correct)
    return prompt

# ------------- YAML GENERATION -------------
def generate_yaml(user_prompt: str) -> str:
    with open(TEMPLATE_PATH, "r") as file:
        template = file.read()
    formatted_prompt = PromptTemplate.from_template(template).format(app_spec=normalize_prompt(user_prompt))
    llm = Ollama(model="mistral")

    try:
        response = llm.invoke(formatted_prompt)

        # ✅ Clean triple backtick markdown if present
        if "```yaml" in response:
            response = response.split("```yaml", 1)[1].strip()
        if "```" in response:
            response = response.split("```", 1)[0].strip()

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(OUTPUT_FILE, "w") as f:
            f.write(response)
        return response
    except Exception as e:
        return f"# Error generating YAML: {str(e)}"

# ----------- STREAMLIT UI ------------------
st.set_page_config(page_title="K8s YAML GenAI", layout="centered")
st.title("🧠 Kubernetes YAML Generator (with Mistral GenAI)")

st.markdown("⚙️ Enter a natural language prompt like:")
st.code("start a flak api with 3 pods on port 5050")
st.code("autoscale a ndoejs app to scale up on port 3035")

sample_prompts = [
    "Deploy a flask app with 2 replicas on port 8000",
    "start a flak api with 3 pods on port 5050",
    "autoscale a ndoejs app to scale up on port 3035",
    "Create deployment and service for a Go app on 9000 with autoscaling from 1 to 4 replicas and CPU trigger at 60%",
]

selected_prompt = st.selectbox("📎 Try a sample prompt:", [""] + sample_prompts)

user_input = st.text_area("✍️ Or write your own prompt:", value=selected_prompt if selected_prompt else "", height=100)

if st.button("🚀 Generate YAML"):
    with st.spinner("Generating Kubernetes YAML..."):
        start_time = time.time()
        result = generate_yaml(user_input)
        elapsed = time.time() - start_time

    st.success(f"✅ YAML generated in {elapsed:.2f} seconds")
    st.code(result, language="yaml")

# Show download button only if YAML exists
if os.path.exists(OUTPUT_FILE):
    with open(OUTPUT_FILE, "rb") as file:
        st.download_button("⬇️ Download deployment.yaml", file, file_name="deployment.yaml", mime="text/yaml")

# Validate YAML before allowing deployment
#try:
    #with open(OUTPUT_FILE, "r") as f:
        #yaml.safe_load(f)
#except Exception as e:
    #st.error("⚠️ YAML is invalid. Fix issues before deploying.")
    #st.code(str(e))
    #st.stop()

st.markdown("---")

if st.button("🚀 Deploy to Kubernetes"):
    try:
        result = subprocess.run(
            ["kubectl", "apply", "-f", OUTPUT_FILE],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            st.success("✅ YAML successfully applied to your cluster!")
            st.code(result.stdout)
        else:
            st.error("❌ Failed to apply YAML. See error below:")
            st.code(result.stderr)
    except Exception as e:
        st.error(f"🚨 Error running kubectl: {str(e)}")
