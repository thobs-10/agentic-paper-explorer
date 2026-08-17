import logging
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(asctime)s]: %(message)s:")

project_name = "src/agentic_paper_explorer"

list_of_files = [
    ".github/workflows/.gitkeep",
    f"{project_name}/__init__.py",
    f"{project_name}/scripts/.gitkeep",
    "notebooks/scratchpad.ipynb",
    f"{project_name}/frontend/__init__.py",
    f"{project_name}/ingestion/api/__init__.py",
    f"{project_name}/ingestion/data_ingestion/__init__.py",
    f"{project_name}/ingestion/pipeline.py",
    f"{project_name}/backend/__init__.py",
    f"{project_name}/backend/api/__init__.py",
    f"{project_name}/backend/database/__init__.py",
    f"{project_name}/backend/prompt_processing/__init__.py",
    f"{project_name}/backend/retrieval/__init__.py",
    f"{project_name}/backend/generation/__init__.py",
    f"{project_name}/backend/security/__init__.py",
    f"{project_name}/backend/pipelines/__init__.py",
    f"{project_name}/monitoring/__init__.py",
    f"{project_name}/monitoring/configs/.gitkeep",
    f"{project_name}/evaluation/__init__.py",
    f"{project_name}/evaluation/configs/.gitkeep",
    f"{project_name}/utils/__init__.py",
    f"{project_name}/utils/main_utils.py",
    f"{project_name}/configs/.gitkeep",
    "tests/__init__.py",
    "README.md",
    "LICENSE",
    ".gitignore",
    ".env",
    ".env.example",
    "Dockerfile",
    "docker-compose.yml",
    "Makefile",
    # "ruff.toml",
    # ".flake8",
    # ".isort.cfg",
    ".pre-commit-config.yaml",
    # ".pylintrc",
    # ".bandit",
    "pyproject.toml",
]

for filepath in list_of_files:
    file_path = Path(filepath)
    filedir, filename = os.path.split(filepath)

    if filedir != "":
        os.makedirs(filedir, exist_ok=True)
        logging.info(f"Created directory: {filedir} for filename: {filename}")
    if (not os.path.exists(filename)) or (os.path.getsize(filename) == 0):
        with open(filepath, "w", encoding="utf-8") as f:
            logging.info(f"Created file: {filename}")
    else:
        logging.info(f"File {filename} already exists.")
