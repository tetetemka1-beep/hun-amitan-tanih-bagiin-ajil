"""Camera, object/face recognition and enrollment; no Tk calls in this module."""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field, replace

import cv2
import numpy as np

from camera_alerts import AlertGate
from camera_store import PHOTO_COUNTS, Store, display_name, local_now, validate_details
from setup_models import MODEL_DIR, ensure_models

LOGGER = logging.getLogger(__name__)
SPECIES = {
    "bird": "Шувуу", "cat": "Муур", "dog": "Нохой", "horse": "Морь",
    "sheep": "Хонь", "cow": "Үхэр", "elephant": "Заан", "bear": "Баавгай",
    "zebra": "Эрээн тахь", "giraffe": "Анааш", "animal": "Амьтан",
    "goat": "Ямаа", "camel": "Тэмээ", "rabbit": "Туулай", "pig": "Гахай",
    "deer": "Буга", "wolf": "Чоно", "fox": "Үнэг", "lion": "Арслан",
    "tiger": "Бар", "snow leopard": "Ирвэс", "donkey": "Илжиг",
    "cheetah": "Гепард", "leopard": "Ирвэс", "monkey": "Сармагчин",
    "panda": "Хулсны баавгай", "rhinoceros": "Хирс", "hippopotamus": "Усны үхэр",
    "kangaroo": "Кенгуру", "squirrel": "Хэрэм", "lynx": "Шилүүс",
}
HUMAN_CLASSES = {"person", "man", "woman", "boy", "girl"}
SPECIES_ALIASES = {"cattle": "cow", "bull": "cow", "brown bear": "bear", "polar bear": "bear"}
DETECTOR_MODEL = "yolov8s-oiv7.pt"
DEFAULT_CONFIDENCE = 0.35


def canonical_species(name):
    """Map actual Open Images/COCO model labels to stable registration keys."""
    name = name.strip().lower()
    if name in HUMAN_CLASSES:
        return "person"
    name = SPECIES_ALIASES.get(name, name)
    # Broad OIV7 labels (Animal, Mammal, Carnivore) cannot name a species.
    return name if name in SPECIES and name != "animal" else None


def suppress_duplicates(objects, iou_threshold=0.60):
    """OIV7 can label one body both Man/Person or Lion/Cat; count it once."""
    kept = []
    for obj in sorted(objects, key=lambda item: item.confidence, reverse=True):
        x1, y1, x2, y2 = obj.bbox
        area = (x2 - x1) * (y2 - y1)
        duplicate = False
        for previous in kept:
            if obj.kind != previous.kind:
                continue
            px1, py1, px2, py2 = previous.bbox
            intersection = max(0, min(x2, px2) - max(x1, px1)) * max(0, min(y2, py2) - max(y1, py1))
            union = area + (px2 - px1) * (py2 - py1) - intersection
            if union > 0 and intersection / union >= iou_threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(obj)
    return kept


def normalized(vector):
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = np.linalg.norm(vector)
    if not np.isfinite(vector).all() or norm < 1e-8:
        raise ValueError("AI загвараас хүчингүй вектор ирлээ.")
    return vector / norm


def best_match(vector, kind, species, gallery, face_threshold=0.50):
    """Cosine similarity, NOT a calibrated probability or measured accuracy."""
    if kind != "human":
        return None, None
    vector = normalized(vector)
    scores = []
    for profile, samples in gallery:
        if profile["kind"] != kind:
            continue
        similarities = np.sort(samples @ vector)
        score = float(np.mean(similarities[-min(3, len(similarities)):]))
        scores.append((score, profile))
    scores.sort(key=lambda item: item[0], reverse=True)
    if not scores:
        return None, None
    score, profile = scores[0]
    threshold, margin = face_threshold, 0.06
    ambiguous = len(scores) > 1 and score - scores[1][0] < margin
    return (profile if score >= threshold and not ambiguous else None), score


@dataclass
class Detection:
    kind: str
    species: str
    confidence: float
    bbox: tuple
    crop: np.ndarray = field(repr=False)
    embedding: np.ndarray | None = field(default=None, repr=False)
    face_size: int = 0
    label: str = ""
    profile_id: str | None = None
    similarity: float | None = None


@dataclass
class FrameResult:
    frame: np.ndarray
    objects: list[Detection]
    fps: float
    captured_at: str


def mirrored_packet(packet):
    """Mirror preview geometry only; enrollment crops and vectors stay original."""
    width = packet.frame.shape[1]
    objects = [replace(obj, bbox=(width - obj.bbox[2], obj.bbox[1],
                                  width - obj.bbox[0], obj.bbox[3])) for obj in packet.objects]
    return replace(packet, frame=cv2.flip(packet.frame, 1), objects=objects)


class RecognitionEngine:
    def __init__(self, progress, cancelled):
        ensure_models(progress, cancelled)
        progress("Хүн, амьтан таних загвар ачаалж байна…")
        import torch
        from ultralytics import YOLO

        torch.set_num_threads(2)
        self.detector = YOLO(str(MODEL_DIR / DETECTOR_MODEL))
        self.class_species = {i: canonical_species(name) for i, name in self.detector.names.items()}
        self.classes = [i for i, name in self.detector.names.items()
                        if self.class_species[i] is not None]
        if "lion" not in self.class_species.values():
            raise ValueError("Сонгосон AI загвар арслангийн ангилалгүй байна.")
        self.face_detector = cv2.FaceDetectorYN_create(
            str(MODEL_DIR / "face_detection_yunet_2023mar.onnx"), "", (320, 320), 0.85)
        self.face_recognizer = cv2.FaceRecognizerSF_create(
            str(MODEL_DIR / "face_recognition_sface_2021dec.onnx"), "")

    def detect(self, frame, confidence, gallery):
        results = self.detector.predict(frame, conf=confidence, classes=self.classes,
                                        imgsz=640, max_det=16, verbose=False, device="cpu")
        height, width = frame.shape[:2]
        objects = []
        for box in results[0].boxes:
            species = self.class_species[int(box.cls[0])]
            if species is None:
                continue
            kind = "human" if species == "person" else "animal"
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            x1, x2 = max(0, x1), min(width, x2)
            y1, y2 = max(0, y1), min(height, y2)
            if x2 - x1 < 16 or y2 - y1 < 16:
                continue
            obj = Detection(kind, species, float(box.conf[0]), (x1, y1, x2, y2),
                            frame[y1:y2, x1:x2].copy())
            obj.label = "Бүртгэлгүй хүн" if kind == "human" else SPECIES.get(species, species)
            objects.append(obj)

        objects = suppress_duplicates(objects)

        faces = []
        if any(obj.kind == "human" for obj in objects):
            self.face_detector.setInputSize((width, height))
            _, detected_faces = self.face_detector.detect(frame)
            if detected_faces is not None:
                faces = list(detected_faces)

        for obj in objects:
            if obj.kind == "human":
                x1, y1, x2, y2 = obj.bbox
                inside = [face for face in faces if
                          x1 <= face[0] + face[2] / 2 <= x2 and
                          y1 <= face[1] + face[3] / 2 <= y2]
                if len(inside) == 1:
                    face = inside[0]
                    obj.face_size = int(min(face[2:4]))
                    if obj.face_size >= 40:
                        obj.crop = self.face_recognizer.alignCrop(frame, face)
                        obj.embedding = normalized(self.face_recognizer.feature(obj.crop))
                if obj.embedding is None:
                    obj.label = "Хүн · нүүрээ харуулна уу"

        for obj in objects:
            if obj.embedding is None:
                continue
            profile, obj.similarity = best_match(obj.embedding, obj.kind, obj.species, gallery)
            if profile is not None:
                obj.profile_id = profile["id"]
                name = display_name(profile)
                obj.label = name
        return objects


class Enrollment:
    def __init__(self, details, profile_id=None):
        self.details = validate_details(details)
        self.profile_id = profile_id
        self.target = PHOTO_COUNTS[self.details["kind"]]
        self.samples = []
        self.last_capture = 0.0
        self.anchor = None
        self.last_gray = None

    def collect(self, objects, now):
        kind = self.details["kind"]
        candidates = [obj for obj in objects if obj.kind == kind]
        if len(candidates) != 1:
            return "Кадрт бүртгүүлэх ганц хүн байлгана уу."
        obj = candidates[0]
        if obj.embedding is None or obj.face_size < 60:
            return "Камер руу ойртож, нүүрээ бүтнээр нь харуулна уу."
        if self.anchor is not None and float(obj.embedding @ self.anchor) < 0.40:
            return "Хүн солигдсон байж болзошгүй. Анхны хүнийг харуулна уу."
        if now - self.last_capture < 0.28:
            return "Толгойгоо / байрлалаа бага зэрэг өөрчлөөрэй."
        gray = cv2.cvtColor(obj.crop, cv2.COLOR_BGR2GRAY)
        if gray.mean() < 35 or gray.mean() > 225:
            return "Гэрэлтүүлгийг тохируулна уу."
        if cv2.Laplacian(gray, cv2.CV_64F).var() < 30:
            return "Дүрс бүдэг байна. Камераа тогтвортой байлгана уу."
        small = cv2.resize(gray, (48, 48)).astype(np.float32)
        if self.last_gray is not None and np.abs(small - self.last_gray).mean() < 1.5:
            return "Өөр өнцгөөс бага зэрэг хөдөлж харуулна уу."
        ok, jpeg = cv2.imencode(".jpg", obj.crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise OSError("Бүртгэлийн зургийг хөрвүүлж чадсангүй.")
        self.samples.append((jpeg.tobytes(), obj.embedding.copy()))
        self.anchor = obj.embedding.copy() if self.anchor is None else self.anchor
        self.last_capture, self.last_gray = now, small
        return "Зураг авч байна · нүүрний байрлалаа аажмаар өөрчлөөрэй."


def open_capture(source):
    backends = [cv2.CAP_ANY]
    import sys
    if isinstance(source, int) and sys.platform == "win32":
        backends.append(cv2.CAP_DSHOW)
    for backend in backends:
        camera = cv2.VideoCapture(source, backend)
        if camera.isOpened():
            if isinstance(source, int):
                camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            return camera
        camera.release()
    raise OSError("Камер нээгдсэнгүй. Индекс, камерын зөвшөөрөл болон бусад программыг шалгана уу.")


class CameraWorker(threading.Thread):
    def __init__(self, store: Store, source=0, confidence=DEFAULT_CONFIDENCE, engine_factory=RecognitionEngine,
                 capture_factory=open_capture):
        super().__init__(name="smart-camera", daemon=True)
        self.store, self.source, self.confidence = store, source, confidence
        self.engine_factory, self.capture_factory = engine_factory, capture_factory
        self.stop_event = threading.Event()
        self.commands = queue.Queue()
        self.events = queue.Queue(maxsize=128)
        self.frames = queue.Queue(maxsize=1)
        self.enrollment = None
        self.gallery = []
        self.ready = False
        self.alert_gate = AlertGate()

    def emit(self, name, value=None):
        # Status traffic is naturally bounded: at most one message per model MB or frame.
        try:
            self.events.put_nowait((name, value))
        except queue.Full:
            if name in {"error", "saved", "stopped", "alert"}:
                try:
                    self.events.get_nowait()
                except queue.Empty:
                    pass
                self.events.put_nowait((name, value))

    def command(self, name, value=None):
        self.commands.put((name, value))

    def handle_commands(self):
        while True:
            try:
                name, value = self.commands.get_nowait()
            except queue.Empty:
                return
            if name == "enroll":
                details, profile_id = value
                try:
                    self.enrollment = Enrollment(details, profile_id)
                    self.emit("enrolling", self.enrollment.target)
                except ValueError as error:
                    self.emit("registration_error", str(error))
            elif name == "cancel":
                self.enrollment = None
                self.emit("cancelled")
            elif name == "reload":
                self.gallery = self.store.gallery()
            elif name == "confidence":
                self.confidence = min(0.95, max(0.10, float(value)))

    def run(self):
        camera = None
        try:
            engine = self.engine_factory(lambda value: self.emit("status", value), self.stop_event)
            if self.stop_event.is_set():
                return
            self.gallery = self.store.gallery()
            self.emit("status", "Камерт холбогдож байна…")
            camera = self.capture_factory(self.source)
            self.ready = True
            self.emit("ready")
            last_events = {}
            smoothed_fps = 0.0
            video_fps = float(camera.get(cv2.CAP_PROP_FPS)) if isinstance(self.source, str) else 0
            video_fps = video_fps if 0 < video_fps <= 240 else 25
            while not self.stop_event.is_set():
                started = time.monotonic()
                self.handle_commands()
                success, frame = camera.read()
                if not success or frame is None or not frame.size:
                    if isinstance(self.source, str):
                        self.emit("status", "Бичлэг дууслаа.")
                        break
                    raise OSError("Камерын дүрс тасарлаа. Холболтыг шалгаад дахин эхлүүлнэ үү.")
                height, width = frame.shape[:2]
                if max(height, width) > 960:
                    scale = 960 / max(height, width)
                    frame = cv2.resize(frame, (int(width * scale), int(height * scale)))
                objects = engine.detect(frame, self.confidence, self.gallery)
                now = time.monotonic()
                was_enrolling = self.enrollment is not None
                if self.enrollment:
                    message = self.enrollment.collect(objects, now)
                    count = len(self.enrollment.samples)
                    self.emit("progress", (count, self.enrollment.target, message))
                    if count == self.enrollment.target:
                        registration = self.enrollment
                        profile_id = self.store.save_registration(
                            registration.details, registration.samples, registration.profile_id)
                        self.enrollment = None
                        self.gallery = self.store.gallery()
                        self.emit("saved", profile_id)

                for alert in self.alert_gate.observe(objects, now, enrolling=was_enrolling):
                    self.emit("alert", alert)

                # Bounded cooldown keys: profile IDs or species, never per-frame IDs.
                for obj in objects:
                    key = obj.profile_id or (obj.kind, obj.species)
                    if now - last_events.get(key, -float("inf")) >= 10:
                        self.store.add_event(obj.kind, obj.label, obj.confidence,
                                             obj.similarity, obj.profile_id)
                        last_events[key] = now
                elapsed = max(time.monotonic() - started, 0.001)
                fps = 1 / elapsed
                smoothed_fps = fps if not smoothed_fps else smoothed_fps * 0.8 + fps * 0.2
                packet = FrameResult(frame, objects, smoothed_fps,
                                     local_now().strftime("%Y-%m-%d %H:%M:%S"))
                try:
                    self.frames.get_nowait()
                except queue.Empty:
                    pass
                self.frames.put_nowait(packet)
                if isinstance(self.source, str):
                    self.stop_event.wait(max(0, 1 / video_fps - elapsed))
        except InterruptedError:
            pass
        except Exception as error:
            LOGGER.exception("Camera worker failed")
            self.emit("error", str(error))
        finally:
            self.ready = False
            if camera is not None:
                camera.release()
            if self.enrollment is not None:
                self.enrollment = None
                self.emit("cancelled")
            self.emit("stopped")
