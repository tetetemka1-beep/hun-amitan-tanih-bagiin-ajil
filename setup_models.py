"""Download public inference weights to this project (once)."""

from __future__ import annotations

import hashlib
import sys
import threading
import urllib.request
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parent / "models"
# URL, minimum size, SHA-256 (or the publisher's hash prefix).
MODELS = {
    "yolov8n-oiv7.pt": (
        "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8n-oiv7.pt",
        5_000_000, ""),
    "face_detection_yunet_2023mar.onnx": (
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx", 200_000,
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    "face_recognition_sface_2021dec.onnx": (
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx", 38_000_000,
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"),
}


def valid_model(path, minimum, digest):
    if not path.is_file() or path.stat().st_size < minimum:
        return False
    if digest:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest().startswith(digest)
    return True


def ensure_models(progress=print, cancelled=None):
    cancelled = cancelled or threading.Event()
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, (url, minimum, digest) in MODELS.items():
        if cancelled.is_set():
            raise InterruptedError("Цуцаллаа.")
        target = MODEL_DIR / name
        if valid_model(target, minimum, digest):
            continue
        partial = target.with_suffix(target.suffix + ".part")
        progress(f"AI загвар татаж байна: {name}")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "SmartCamera/1.0"})
            with urllib.request.urlopen(request, timeout=30) as response, partial.open("wb") as output:
                size = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                previous_mb = -1
                while True:
                    if cancelled.is_set():
                        raise InterruptedError("Цуцаллаа.")
                    block = response.read(256 * 1024)
                    if not block:
                        break
                    output.write(block)
                    downloaded += len(block)
                    mb = downloaded // 1_048_576
                    if mb != previous_mb:
                        suffix = f" / {size / 1_048_576:.1f} MB" if size else " MB"
                        progress(f"{name}: {downloaded / 1_048_576:.1f}{suffix}")
                        previous_mb = mb
            if not valid_model(partial, minimum, digest):
                raise OSError(f"Татсан загвар дутуу эсвэл эвдэрсэн байна: {name}")
            partial.replace(target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
    progress("AI загварууд бэлэн.")


if __name__ == "__main__":
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ensure_models()
