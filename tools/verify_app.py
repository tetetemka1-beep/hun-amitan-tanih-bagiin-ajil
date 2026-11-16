"""Optional integration checks. Uses a temporary database, never real registrations."""

import argparse
import importlib.util
import queue
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from camera_engine import CameraWorker, Detection, FrameResult, RecognitionEngine, best_match, open_capture
from camera_alerts import AlertGate
from camera_store import Store, local_now


def samples():
    assets = ROOT / "tests" / "fixtures"
    assets.mkdir(exist_ok=True)
    for name, url in {
        "dog.jpg": "https://raw.githubusercontent.com/pytorch/hub/master/images/dog.jpg",
        "lena.jpg": "https://raw.githubusercontent.com/opencv/opencv/master/samples/data/lena.jpg",
        "lion.jpg": "https://live.staticflickr.com/10/11232963_3a615c0052_o.jpg",
    }.items():
        path = assets / name
        if not path.exists():
            request = urllib.request.Request(url, headers={"User-Agent": "SmartCamera/1.0 (local model test)"})
            with urllib.request.urlopen(request, timeout=30) as response:
                path.write_bytes(response.read())
        print("Sample ready:", name)


def verify_models():
    engine = RecognitionEngine(print, threading.Event())
    empty = engine.detect(np.zeros((480, 640, 3), dtype=np.uint8), 0.5, [])
    assert not empty, "Empty frame must not contain detections"
    assets = Path(importlib.util.find_spec("ultralytics").origin).parent / "assets"
    human_path = ROOT / "tests" / "fixtures" / "lena.jpg"
    frame = cv2.imdecode(np.frombuffer(human_path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    people = engine.detect(frame, 0.4, [])
    faces = [obj for obj in people if obj.kind == "human" and obj.embedding is not None]
    assert faces, "Real face must produce an SFace embedding"
    assert faces[0].embedding.shape == (128,)
    faces_again = engine.detect(cv2.flip(frame, 1), 0.4, [])
    alternate = next(obj for obj in faces_again if obj.kind == "human" and obj.embedding is not None)
    profile = dict(id="test", kind="human", species="person", surname="Тест", name="Нэр")
    matched, score = best_match(alternate.embedding, "human", "person",
                                [(profile, np.stack([faces[0].embedding] * 3))])
    assert matched is not None, f"Same-face alternate view did not match: {score}"
    print(f"Human detection + SFace + changed-view identity: OK (similarity {score:.3f})")
    # Unrelated faces should remain unknown.
    other = cv2.imdecode(np.frombuffer((assets / "zidane.jpg").read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    for obj in engine.detect(other, 0.4, []):
        if obj.kind == "human" and obj.embedding is not None:
            match, _ = best_match(obj.embedding, "human", "person",
                                  [(profile, np.stack([faces[0].embedding] * 3))])
            assert match is None, "Unregistered face must stay unknown"
    animal_path = ROOT / "tests" / "fixtures" / "dog.jpg"
    animal_frame = cv2.imdecode(np.frombuffer(animal_path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    # Match the camera worker's maximum input size.
    height, width = animal_frame.shape[:2]
    scale = min(1, 960 / max(height, width))
    animal_frame = cv2.resize(animal_frame, (int(width * scale), int(height * scale)))
    animals = engine.detect(animal_frame, 0.5, [])
    dogs = [obj for obj in animals if obj.kind == "animal" and obj.species == "dog"]
    assert dogs and dogs[0].embedding is None and dogs[0].profile_id is None
    print(f"Dog detection without animal enrollment: OK (detection {dogs[0].confidence:.3f})")
    lion_path = ROOT / "tests" / "fixtures" / "lion.jpg"
    lion_frame = cv2.imdecode(np.frombuffer(lion_path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    height, width = lion_frame.shape[:2]
    scale = min(1, 960 / max(height, width))
    lion_frame = cv2.resize(lion_frame, (int(width * scale), int(height * scale)))
    lions = [obj for obj in engine.detect(lion_frame, 0.35, []) if obj.species == "lion"]
    assert len(lions) == 1 and lions[0].embedding is None, "Lion must be detected as Lion exactly once"
    assert lions[0].label == "Арслан"
    alternate = engine.detect(cv2.flip(lion_frame, 1), 0.35, [])
    assert any(obj.species == "lion" for obj in alternate), "Flipped lion photo must stay Lion"
    gate = AlertGate()
    assert gate.observe(lions, 1) == []
    assert gate.observe(lions, 2) == []
    assert gate.observe(lions, 3)[0]["kind"] == "animal"
    unknown_gate = AlertGate(stable_frames=1)
    assert unknown_gate.observe(people, 1)[0]["kind"] == "unknown_human"
    known_profile = dict(id="face-test", kind="human", surname="Тест", name="Нэр", species="person")
    known = engine.detect(frame, 0.4, [(known_profile, np.stack([faces[0].embedding] * 50))])
    assert any(obj.profile_id == "face-test" for obj in known)
    assert unknown_gate.observe(known, 40) == []
    print(f"Lion + animal alert + unknown/known face notifications: OK (lion detection {lions[0].confidence:.3f})")


def verify_camera():
    with tempfile.TemporaryDirectory(prefix="camera_live_check_") as temp:
        worker = CameraWorker(Store(Path(temp) / "test.sqlite3"), 0)
        worker.start()
        received = 0
        deadline = time.monotonic() + 40
        try:
            while received < 5 and time.monotonic() < deadline:
                try:
                    frame = worker.frames.get(timeout=0.2)
                    assert frame.frame.size and frame.fps > 0
                    received += 1
                except queue.Empty:
                    if not worker.is_alive():
                        break
        finally:
            worker.stop_event.set()
            worker.join(timeout=10)
        assert not worker.is_alive(), "Camera worker did not stop"
        errors = [value for name, value in list(worker.events.queue) if name == "error"]
        assert not errors, errors
        assert received >= 5, "Camera + AI pipeline did not produce five frames"
        print("Webcam + real AI worker: OK", frame.frame.shape, f"{frame.fps:.1f} FPS")
    reopened = open_capture(0)
    try:
        assert reopened.read()[0], "Camera must reopen after release"
        print("Webcam release and reopen after AI processing: OK")
    finally:
        reopened.release()


def verify_gui():
    import customtkinter as ctk
    from PIL import ImageGrab
    from uhaalag_camera import SmartCameraApp

    rng = np.random.default_rng(1)
    crop = rng.integers(45, 210, (112, 112, 3), dtype=np.uint8)
    _, jpeg = cv2.imencode(".jpg", crop)
    human_vector = np.zeros(128, np.float32)
    human_vector[0] = 1
    with tempfile.TemporaryDirectory(prefix="camera_gui_check_") as temp:
        store = Store(Path(temp) / "test.sqlite3")
        key = store.save_registration(dict(kind="human", surname="Дорж", name="Бат", species="person"),
                                      [(jpeg.tobytes(), human_vector)] * 50)
        ctk.set_appearance_mode("dark")
        app = SmartCameraApp(store=store)
        sound_calls = []
        app.sound_player.play = lambda kind: sound_calls.append(kind) or True
        callback_errors = []
        app.report_callback_exception = lambda *error: callback_errors.append(error)
        app.update()
        assert app.profile_tree.exists(key)
        app.tabs.set("Бүртгэлүүд")
        app.refresh_profiles(key)
        app.move_photo(1)
        app.edit_vars["name"].set("Саруул")
        app.edit_profile()
        assert next(p for p in store.profiles() if p["id"] == key)["name"] == "Саруул"
        app.update()
        assert app.photo_count_label.cget("text").startswith("1 / 50")
        frame = np.full((480, 640, 3), (34, 27, 18), dtype=np.uint8)
        objects = [Detection("human", "person", 0.96, (60, 60, 270, 420), crop,
                             human_vector, 90, "Дорж Саруул", key, 0.82),
                   Detection("animal", "lion", 0.94, (330, 230, 590, 425), crop,
                             None, 0, "Арслан")]
        app.tabs.set("Шууд камер")
        app.live_label.configure(text="●  ТУРШИЛТЫН ДҮРС")
        app.render_packet(FrameResult(frame, objects, 14.2, local_now().strftime("%Y-%m-%d %H:%M:%S")))
        app.update()
        assert not hasattr(app, "animal_button"), "Animal enrollment control must be removed"
        assert app.stat_labels["human"].cget("text") == "1"
        assert app.stat_labels["animal"].cget("text") == "1"
        original = np.asarray(app.rendered_image).copy()
        app.mirror_switch.toggle()
        app.change_mirror()
        assert app.mirror_var.get()
        assert store.get_setting("mirror_preview") == "1"
        # Use a point outside the boxes/timestamp; pixel content must flip, text is drawn afterwards.
        assert app.last_packet.objects[0].bbox == (60, 60, 270, 420)
        app.mirror_switch.toggle()
        app.change_mirror()
        assert not app.mirror_var.get()
        np.testing.assert_array_equal(np.asarray(app.rendered_image), original)
        app.update()
        class ReadyWorker:
            ready = True
            events = queue.Queue()
            frames = queue.Queue()
            stop_event = threading.Event()

            def __init__(self):
                self.commands = []

            def is_alive(self):
                return True

            def command(self, name, value=None):
                self.commands.append((name, value))

        app.worker = ReadyWorker()
        objects[0].profile_id = None
        objects[0].label = "Бүртгэлгүй хүн"
        app.render_packet(FrameResult(frame, objects, 14.2, local_now().strftime("%Y-%m-%d %H:%M:%S")))
        animal_alert = {"kind": "animal", "message": "Амьтан илэрлээ: Арслан", "count": 1}
        app.handle_alert(animal_alert)
        assert sound_calls == ["animal"]
        assert app.dialog is None
        app.animal_alarm_var.set(False)
        app.change_alert_settings()
        app.handle_alert(animal_alert)
        assert sound_calls == ["animal"], "Muted animal alert must stay silent"
        assert store.get_setting("animal_alarm") == "0"
        app.handle_alert({"kind": "unknown_human", "message": "Бүртгэлгүй хүн илэрлээ", "count": 1})
        assert app.visible_notices == {"animal", "unknown_human"}
        assert sound_calls == ["animal", "unknown_human"]
        assert app.dialog is None, "A notification must not automatically open the enrollment form"
        app.update()
        output = ROOT / "camera_data" / "previews"
        output.mkdir(parents=True, exist_ok=True)
        # Capture this Tk window only, even when another app is in front of it.
        ImageGrab.grab(window=app.winfo_id()).save(output / "gui_preview.png")
        app.notice_register_button.invoke()
        app.update()
        assert app.dialog is not None
        with patch("uhaalag_camera.messagebox.showerror") as showerror:
            app.dialog.event_generate("<Return>")
            app.update()
            assert showerror.called, "Empty name must be rejected"
        fields = sorted((widget for widget in app.dialog.winfo_children() if isinstance(widget, ctk.CTkEntry)),
                        key=lambda widget: widget.grid_info()["row"])
        fields[0].insert(0, "Тест")
        fields[1].insert(0, "Шинэ хүн")
        app.dialog.event_generate("<Return>")
        app.update()
        assert app.dialog is None and app.enrollment_active
        assert app.worker.commands[-1][0] == "enroll"
        assert app.worker.commands[-1][1][0]["kind"] == "human"
        app.worker.events.put(("cancelled", None))
        app.poll_worker()
        assert not app.enrollment_active
        app.worker = None
        with patch("uhaalag_camera.messagebox.askyesno", return_value=True):
            app.delete_profile()
        assert store.profiles() == []
        app.update()
        app.on_close()
        assert not callback_errors, callback_errors
        print("GUI, human notice -> enrollment, animal alarm/mute, mirror, gallery/edit/delete: OK")
        print("Preview:", output / "gui_preview.png")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-samples", action="store_true")
    parser.add_argument("--models", action="store_true")
    parser.add_argument("--camera", action="store_true")
    parser.add_argument("--gui", action="store_true")
    args = parser.parse_args()
    if args.download_samples:
        samples()
    if args.models:
        verify_models()
    if args.camera:
        verify_camera()
    if args.gui:
        verify_gui()
