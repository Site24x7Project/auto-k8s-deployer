import os

def apply_yaml(file_path):
    os.system(f"kubectl apply -f {file_path}")

apply_yaml("output/deployment.yaml")
