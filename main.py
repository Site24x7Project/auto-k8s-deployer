from langchain.llms import Ollama
from langchain.prompts import PromptTemplate
import os


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
        "autoscaling from 1 to 4 replicas": "add a HorizontalPodAutoscaler to scale between 1 and 4 replicas",
        "autoscaling from 2 to 5 replicas": "add a HorizontalPodAutoscaler to scale between 2 and 5 replicas",
        "cpu trigger at 60%": "based on 60% CPU usage",
        "trigger at 60% cpu": "based on 60% CPU usage",
        "scaler": "HorizontalPodAutoscaler",
        "flak": "flask",  # typo example
        "flsk": "flask",
        "ndoe": "node",
        "gonode": "go and node app"
    }

    for wrong, correct in replacements.items():
        prompt = prompt.replace(wrong, correct)

    return prompt


with open("prompts/kube_template.txt", "r") as file:
    template = file.read()


user_input = input("Enter app spec (e.g. Deploy a Flask app with 2 replicas on port 5000):\n")

normalized_input = normalize_prompt(user_input)

prompt = PromptTemplate.from_template(template).format(app_spec=normalized_input)

llm = Ollama(model="mistral")

try:
    response = llm.invoke(prompt)
except Exception as e:
    print(" Error generating YAML from LLM:", e)
    response = "# Generation failed. Please rephrase your prompt or try again."

os.makedirs("output", exist_ok=True)
with open("output/deployment.yaml", "w") as f:
    f.write(response)

print("\n YAML saved to output/deployment.yaml")
