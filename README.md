# GenAI-Powered Kubernetes YAML Generator

A full-stack AI-powered tool that converts natural language prompts into production-ready Kubernetes Deployment and Service YAMLs files. Built using Mistral (via Ollama), LangChain, and Streamlit with support for prompt normalization, autoscaling logic, and one-click deployment to Minikube.

---

## Features

* Converts natural language to valid Kubernetes YAML
* Handles typos, vague dev language, and autoscaling keywords
* Uses Mistral LLM via Ollama and LangChain
* Adds autoscaling (HPA) logic when prompted
* YAML is downloadable and deployable with `kubectl`
* Built-in Streamlit UI with sample prompts
* Supports Flask, Node.js, Go apps, and more

---

## Project Structure

```
kube-genai/
├── app.py                # Streamlit frontend UI
├── main.py               # CLI entry for prompt → YAML generation
├── apply_yaml.py         # Script to apply YAML using kubectl
├── prompts/
│   └── kube_template.txt # YAML prompt template
├── output/
│   └── deployment.yaml   # Generated YAML saved here
├── requirements.txt
├── sample_output.yaml
├── deployment.yaml
└── README.md
```

---

## Installation

```bash
# Clone the repo
git clone https://github.com/your-username/kube-genai.git
cd kube-genai

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

## Run Ollama (Mistral)

Start Ollama with Mistral model:

```bash
ollama run mistral
```

> This must be running in a separate terminal before using the app.

---

## Run the App (Streamlit)

Make sure Minikube is installed and running:

```bash
minikube start
```

Then run the Streamlit app:

```bash
streamlit run app.py
```

Or use the CLI version:

```bash
python main.py
```

---

## Sample Prompts

Use any of the following examples to test:

* Deploy a flask app with 2 replicas on port 8000
* Start a flak API with 3 pods on port 5050
* Autoscale a Node.js app to scale up on port 3035
* Create deployment and service for a Go app on port 9000 with autoscaling from 1 to 4 replicas and CPU trigger at 60%

---

## Tech Stack

* Python, Streamlit
* LangChain, Mistral (via Ollama)
* Kubernetes, Minikube, YAML
* Prompt Engineering
* `kubectl`, CLI automation

---

## Author

**Aswathi Vipin**
[LinkedIn](https://www.linkedin.com/in/aswathivk)

---

## License

MIT License
See the [LICENSE](LICENSE) file for details.
