
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
from ultralytics import YOLO

VISION_DIR = Path(__file__).resolve().parents[1]
MODEL_DIR = VISION_DIR / "models"

SOURCE_MODEL = MODEL_DIR / "yolov11-3d-print-failure-detection"
MODEL_PATH = MODEL_DIR / "layerlock.pt"

# Give the downloaded weights a .pt extension for Ultralytics.
if not MODEL_PATH.exists():
    shutil.copyfile(SOURCE_MODEL, MODEL_PATH)

# Load the pretrained model once.
model = YOLO(str(MODEL_PATH))


def detect_failure(frame, conf=0.25):
    """Detect 3D-print defects in an OpenCV image."""

    results = model.predict(
        source=frame,
        conf=conf,
        verbose=False
    )

    result = results[0]
    detections = []

    for box in result.boxes:
        class_id = int(box.cls[0].item())
        label = result.names[class_id].lower()
        confidence = float(box.conf[0].item())

        detections.append({
            "type": label,
            "confidence": round(confidence, 4)
        })

    # Only spaghetti failures trigger the initial MVP detector.
    spaghetti = [
        detection
        for detection in detections
        if detection["type"] == "spaghetti"
    ]

    highest_confidence = max(
        (detection["confidence"] for detection in spaghetti),
        default=0.0
    )

    response = {
        "failure_detected": len(spaghetti) > 0,
        "failure_type": "spaghetti" if spaghetti else None,
        "confidence": highest_confidence,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "detections": detections
    }

    return response, result.plot()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python vision/src/detector.py <image_path>")
        sys.exit(1)

    image_path = Path(sys.argv[1])
    frame = cv2.imread(str(image_path))

    if frame is None:
        raise ValueError(f"Could not read image: {image_path}")

    response, annotated_image = detect_failure(frame)

    print(json.dumps(response, indent=2))

    output_path = VISION_DIR / "results" / "detection_result.jpg"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), annotated_image)

    print(f"Detection image saved to: {output_path}")
