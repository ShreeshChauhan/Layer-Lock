from pathlib import Path
from huggingface_hub import hf_hub_download

MODEL_DIR = Path(__file__).parent / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

model_path = hf_hub_download(
    repo_id="ApatheticWithoutTheA/3D-Print-Failure-Detector",
    filename="yolov11-3d-print-failure-detection",
    local_dir=str(MODEL_DIR),
)

print(f"Model downloaded successfully: {model_path}")
