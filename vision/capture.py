
import cv2
import time
from pathlib import Path

# Store captured frames inside the vision directory
OUTPUT_DIR = Path(__file__).parent / "captures"
OUTPUT_DIR.mkdir(exist_ok=True)

# Connect to the default webcam
camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)

if not camera.isOpened():
    raise RuntimeError("Could not open webcam.")

print("LayerLock camera monitoring started.")
print("Press Q to quit.")

last_capture = time.monotonic() - 3

try:
    while True:
        success, frame = camera.read()

        if not success:
            print("Failed to read camera frame.")
            break

        # Save one frame every three seconds
        if time.monotonic() - last_capture >= 3:
            filename = f"frame_{int(time.time() * 1000)}.jpg"
            filepath = OUTPUT_DIR / filename

            cv2.imwrite(str(filepath), frame)
            print(f"Captured: {filepath.name}")

            last_capture = time.monotonic()

        # Show the live camera feed
        cv2.imshow("LayerLock Camera", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

finally:
    camera.release()
    cv2.destroyAllWindows()
