# LayerLock vision

Camera-based spaghetti detection using OpenCV and a pretrained Ultralytics YOLO11 model. The publisher sends confidence readings to the LayerLock backend, which owns arming, automatic pauses, incident logging, and recovery.

## Run

Install `vision/requirements.txt` in the root Python environment and download the weights:

```powershell
.\.venv\Scripts\python.exe vision/src/download_model.py
```

Use **Enable vision** in the dashboard to start the managed worker. For a separate publisher, see [Pi inference](docs/PI_INFERENCE.md). Live video and inference operate independently.

## Layout

- `src/`: capture, inference, publishing, and evaluation programs.
- `config/`: evaluation regions of interest.
- `datasets/`: tracked dataset metadata and video manifests.
- `tests/`: automated tests and small image fixtures.
- `docs/`: inference and evaluation guides.
- `models/`, `results/`, and downloaded footage: local generated files, excluded from Git.

The pretrained weights come from [3D-Print-Failure-Detector](https://huggingface.co/ApatheticWithoutTheA/3D-Print-Failure-Detector). The current intervention signal uses the highest spaghetti confidence in a frame.

See [testing and validation](../docs/TESTING.md), [dataset evaluation](docs/DATASET_EVALUATION.md), and [video evaluation](docs/TEST_VIDEOS.md).
