import json
import time

import cv2

from detector import detect_failure
from pi_camera import get_pi_frame


SNAPSHOT_URL = "http://10.26.82.5/webcam/?action=snapshot"
INTERVAL = 3


def main():
    print("LayerLock Raspberry Pi monitoring started.")
    print("Press Q to exit.")

    try:
        while True:
            start = time.monotonic()

            try:
                frame = get_pi_frame(SNAPSHOT_URL)

                result, annotated_frame = detect_failure(frame)

                print(json.dumps(result, indent=2))

                cv2.imshow("LayerLock Pi Camera", annotated_frame)

            except Exception as error:
                print(f"Camera error: {error}")

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

            elapsed = time.monotonic() - start
            time.sleep(max(0, INTERVAL - elapsed))

    except KeyboardInterrupt:
        pass

    finally:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()