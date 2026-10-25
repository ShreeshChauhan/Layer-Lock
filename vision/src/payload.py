from datetime import datetime, timezone


def create_vision_payload(detection_result):
    """
    Convert YOLO detection output to the agreed
    LayerLock vision-to-backend JSON contract.
    """

    confidence = detection_result.get("confidence", 0.0)
    failure_type = detection_result.get("failure_type")

    # Convert 0.0–1.0 confidence to 0–100 percentage
    camera_confidence = round(confidence * 100)

    return {
        "camera_confidence": camera_confidence,
        "failure_type": failure_type,
        "timestamp": datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
    }
