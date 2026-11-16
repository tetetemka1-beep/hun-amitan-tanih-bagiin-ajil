import csv
import itertools
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from camera_engine import (CameraWorker, Detection, Enrollment, FrameResult, best_match,
                           canonical_species, mirrored_packet, normalized, open_capture,
                           suppress_duplicates)
from camera_store import Store, local_now


def vector(kind="human", index=0):
    result = np.zeros(128 if kind == "human" else 512, dtype=np.float32)
    result[index] = 1
    return result


def details(kind="human", name="Бат"):
    return dict(kind=kind, surname="Дорж" if kind == "human" else "",
                name=name, species="person" if kind == "human" else "dog", note="Туршилт")


def image(seed=1):
    return np.random.default_rng(seed).integers(50, 205, (112, 112, 3), dtype=np.uint8)


def sample(kind="human", seed=1):
    success, jpeg = cv2.imencode(".jpg", image(seed))
    assert success
    return jpeg.tobytes(), vector(kind)


def detection(kind="human", seed=1, feature=None):
    return Detection(kind, "person" if kind == "human" else "dog", 0.95,
                     (10, 10, 120, 120), image(seed),
                     vector(kind) if feature is None else feature, 80,
                     "Бүртгэлгүй хүн" if kind == "human" else "Нохой")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="camera_test_")
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "Монгол хавтас" / "test.sqlite3")

    def register(self, kind="human"):
        return self.store.save_registration(details(kind), [sample(kind)] * (50 if kind == "human" else 20))

    def test_complete_enrollment_survives_reopen_and_matches_name(self):
        key = self.register()
        reopened = Store(self.store.path)
        self.assertEqual(reopened.profiles()[0]["photo_count"], 50)
        profile, score = best_match(vector(), "human", "person", reopened.gallery())
        self.assertEqual(profile["id"], key)
        self.assertEqual(profile["surname"], "Дорж")
        self.assertAlmostEqual(score, 1.0)
        photo = cv2.imdecode(np.frombuffer(reopened.photo(key), dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(photo.shape, (112, 112, 3))

    def test_partial_registration_never_appears(self):
        for kind, count in (("human", 49), ("animal", 19)):
            with self.assertRaises(ValueError):
                self.store.save_registration(details(kind), [sample(kind)] * count)
        self.assertEqual(self.store.profiles(), [])

    def test_invalid_retake_keeps_old_photos_and_name(self):
        key = self.register()
        old_photo = self.store.photo(key)
        with self.assertRaises(ValueError):
            self.store.save_registration(details(name="Шинэ нэр"), [sample()] * 49, key)
        self.assertEqual(self.store.photo(key), old_photo)
        self.assertEqual(self.store.profiles()[0]["name"], "Бат")

    def test_complete_retake_replaces_exactly_fifty_photos(self):
        key = self.register()
        replacement = sample(seed=10)
        self.store.save_registration(details(name="Саруул"), [replacement] * 50, key)
        self.assertEqual(self.store.photo(key), replacement[0])
        self.assertEqual(self.store.profiles()[0]["photo_count"], 50)
        self.assertEqual(self.store.profiles()[0]["name"], "Саруул")

    def test_edit_keeps_photos_and_updates_recognized_name(self):
        key = self.register()
        self.store.edit(key, details("human", "Саруул"))
        profile, _ = best_match(vector(), "human", "person", self.store.gallery())
        self.assertEqual(profile["name"], "Саруул")
        self.assertEqual(self.store.profiles()[0]["photo_count"], 50)

    def test_animal_registration_is_rejected_in_storage_and_capture(self):
        with self.assertRaisesRegex(ValueError, "Зөвхөн хүн"):
            self.store.save_registration(details("animal"), [sample("animal")] * 20)
        with self.assertRaises(ValueError):
            Enrollment(details("animal"))
        self.assertEqual(self.store.profiles(), [])

    def test_legacy_animal_data_is_preserved_but_not_used_or_exported(self):
        key = self.register()
        photo, feature = sample("animal")
        with self.store.connect() as db:
            db.execute("INSERT INTO profiles VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       ("legacy-animal", "animal", "", "Банхар", "dog", "", "2026-11-16", "2026-11-16"))
            db.execute("INSERT INTO samples(profile_id, photo, vector) VALUES (?, ?, ?)",
                       ("legacy-animal", photo, feature.tobytes()))
        reopened = Store(self.store.path)
        self.assertEqual([profile["id"] for profile in reopened.profiles()], [key])
        self.assertEqual(len(reopened.gallery()), 1)
        self.assertEqual(reopened.gallery()[0][1].shape[1], 128)
        self.assertEqual(reopened.photo("legacy-animal"), photo)
        path = Path(self.temp.name) / "people.csv"
        reopened.export_csv(path)
        self.assertNotIn("Банхар", path.read_text(encoding="utf-8-sig"))

    def test_delete_cascades_photos_but_preserves_event_history(self):
        key = self.register()
        self.store.add_event("human", "Дорж Бат", 0.9, 0.8, key)
        self.store.delete(key)
        self.assertEqual(self.store.profiles(), [])
        self.assertEqual(self.store.gallery(), [])
        self.assertIsNone(self.store.photo(key))
        self.assertEqual(self.store.events()[0]["label"], "Дорж Бат")
        self.assertIsNone(self.store.events()[0]["profile_id"])

    def test_event_with_just_deleted_profile_does_not_fail(self):
        key = self.register()
        self.store.delete(key)
        self.store.add_event("human", "Бат", 0.9, profile_id=key)
        self.assertIsNone(self.store.events()[0]["profile_id"])

    def test_csv_preserves_mongolian_and_escapes_formulas(self):
        key = self.register()
        self.store.edit(key, details(name="=SUM(1)"))
        path = Path(self.temp.name) / "бүртгэл.csv"
        self.store.export_csv(path)
        with path.open(encoding="utf-8-sig", newline="") as file:
            row = next(csv.DictReader(file))
        self.assertEqual(row["surname"], "Дорж")
        self.assertEqual(row["name"], "'=SUM(1)")

    def test_invalid_embeddings_and_empty_names_are_rejected(self):
        for feature in (np.zeros(128), np.full(128, np.nan), vector("animal")):
            with self.assertRaises(ValueError):
                self.store.save_registration(details(), [(sample()[0], feature)] * 50)
        with self.assertRaises(ValueError):
            self.store.save_registration(details(name=" "), [sample()] * 50)
        self.assertEqual(self.store.profiles(), [])

    def test_mirror_setting_survives_restart_without_changing_registration(self):
        key = self.register()
        self.assertEqual(self.store.get_setting("mirror_preview", "0"), "0")
        self.store.set_setting("mirror_preview", "1")
        reopened = Store(self.store.path)
        self.assertEqual(reopened.get_setting("mirror_preview", "0"), "1")
        self.assertEqual(reopened.profiles()[0]["id"], key)
        reopened.set_setting("mirror_preview", "0")
        self.assertEqual(self.store.get_setting("mirror_preview"), "0")


class RecognitionTests(unittest.TestCase):
    def test_open_images_labels_preserve_stable_registration_species(self):
        self.assertEqual(canonical_species("Lion"), "lion")
        self.assertEqual(canonical_species("Tiger"), "tiger")
        self.assertEqual(canonical_species("Cattle"), "cow")
        self.assertEqual(canonical_species("Man"), "person")
        self.assertEqual(canonical_species("Woman"), "person")
        self.assertIsNone(canonical_species("Animal"))
        self.assertIsNone(canonical_species("Mammal"))
        self.assertIsNone(canonical_species("Sculpture"))

    def test_overlapping_lion_and_cat_do_not_double_count(self):
        lion, cat = detection("animal"), detection("animal")
        lion.species, lion.confidence = "lion", 0.92
        cat.species, cat.confidence = "cat", 0.60
        self.assertEqual(suppress_duplicates([cat, lion]), [lion])

    def test_separate_animals_and_overlapping_human_are_preserved(self):
        first, second, person = detection("animal"), detection("animal"), detection()
        second.bbox = (140, 10, 250, 120)
        result = suppress_duplicates([first, second, person])
        self.assertEqual(len(result), 3)

    def test_mirror_keeps_boxes_aligned_and_enrollment_data_unchanged(self):
        frame = np.zeros((150, 320, 3), np.uint8)
        frame[:, :20] = (10, 80, 200)
        obj = detection()
        obj.bbox = (10, 15, 70, 100)
        packet = FrameResult(frame, [obj], 8.0, "2026-11-16 12:00:00")
        preview = mirrored_packet(packet)
        np.testing.assert_array_equal(preview.frame[:, -20:], frame[:, :20][:, ::-1])
        self.assertEqual(preview.objects[0].bbox, (250, 15, 310, 100))
        self.assertEqual(obj.bbox, (10, 15, 70, 100))
        self.assertIs(preview.objects[0].crop, obj.crop)
        self.assertIs(preview.objects[0].embedding, obj.embedding)
        np.testing.assert_array_equal(mirrored_packet(preview).frame, frame)
        self.assertEqual(mirrored_packet(preview).objects[0].bbox, obj.bbox)

    def test_lookalike_and_below_threshold_stay_unknown(self):
        first, second = details(), details(name="Өөр хүн")
        gallery = [(first, np.stack([vector()] * 3)), (second, np.stack([vector()] * 3))]
        self.assertIsNone(best_match(vector(), "human", "person", gallery)[0])
        self.assertIsNone(best_match(vector(index=1), "human", "person", gallery[:1])[0])

    def test_animal_match_never_crosses_species(self):
        gallery = [(details("animal"), np.stack([vector("animal")] * 3))]
        self.assertIsNone(best_match(vector("animal"), "animal", "cat", gallery)[0])
        self.assertIsNone(best_match(vector("animal"), "animal", "dog", gallery)[0])

    def test_enrollment_requires_one_subject_visible_face_and_different_frames(self):
        enrollment = Enrollment(details())
        enrollment.collect([detection(), detection()], 100)
        self.assertEqual(len(enrollment.samples), 0)
        face_hidden = detection()
        face_hidden.embedding = None
        enrollment.collect([face_hidden], 101)
        enrollment.collect([detection()], 102)
        enrollment.collect([detection()], 103)  # Identical frame, should be skipped.
        enrollment.collect([detection(seed=2)], 104)
        enrollment.collect([detection(seed=3, feature=vector(index=1))], 105)
        self.assertEqual(len(enrollment.samples), 2)

    def test_blurred_and_dark_photos_do_not_count(self):
        enrollment = Enrollment(details())
        for pixel in (0, 120, 255):
            obj = detection()
            obj.crop[:] = pixel
            enrollment.collect([obj], 100 + pixel)
        self.assertEqual(len(enrollment.samples), 0)

    def test_fixed_local_timezone_and_zero_vector(self):
        self.assertEqual(local_now().utcoffset().total_seconds(), 8 * 3600)
        with self.assertRaises(ValueError):
            normalized(np.zeros(128))


class FakeCapture:
    def __init__(self, count=70):
        self.count = count
        self.index = 0
        self.released = False

    def read(self):
        self.index += 1
        return (True, image(self.index)) if self.index <= self.count else (False, None)

    def get(self, _property):
        return 25

    def release(self):
        self.released = True


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="camera_worker_test_")
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "test.sqlite3")

    def worker(self, kind="human", count=70, engine_error=False):
        capture = FakeCapture(count)

        class FakeEngine:
            def __init__(self, progress, cancelled):
                pass

            def detect(self, frame, confidence, gallery):
                if engine_error:
                    raise RuntimeError("Test inference failure")
                return [detection(kind, capture.index)]

        worker = CameraWorker(self.store, "test.avi", engine_factory=FakeEngine,
                              capture_factory=lambda source: capture)
        return worker, capture

    def test_complete_human_enrollment_and_bounded_preview(self):
        worker, capture = self.worker()
        worker.command("enroll", (details(), None))
        with patch("camera_engine.time.monotonic", side_effect=itertools.count(100, 0.5)):
            worker.start()
            worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertTrue(capture.released)
        self.assertEqual(worker.frames.qsize(), 1)
        self.assertEqual(self.store.profiles()[0]["photo_count"], 50)

    def test_animal_generates_alert_without_registration(self):
        worker, capture = self.worker("animal", count=6)
        worker.run()
        self.assertTrue(capture.released)
        alerts = [value for name, value in list(worker.events.queue) if name == "alert"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["kind"], "animal")
        self.assertEqual(self.store.profiles(), [])

    def test_invalid_animal_enrollment_does_not_stop_camera_alerts(self):
        worker, capture = self.worker("animal", count=6)
        worker.command("enroll", (details("animal"), None))
        worker.run()
        events = list(worker.events.queue)
        self.assertTrue(any(name == "registration_error" for name, _ in events))
        self.assertTrue(any(name == "alert" for name, _ in events))
        self.assertFalse(any(name == "error" for name, _ in events))
        self.assertTrue(capture.released)

    def test_eof_discards_incomplete_enrollment(self):
        worker, capture = self.worker(count=3)
        worker.command("enroll", (details(), None))
        worker.run()
        self.assertTrue(capture.released)
        self.assertEqual(self.store.profiles(), [])
        self.assertIsNone(worker.enrollment)

    def test_inference_error_releases_camera_and_reports_failure(self):
        worker, capture = self.worker(engine_error=True)
        with self.assertLogs("camera_engine", level="ERROR"):
            worker.run()
        self.assertTrue(capture.released)
        events = list(worker.events.queue)
        self.assertTrue(any(name == "error" for name, _ in events))
        self.assertEqual(events[-1][0], "stopped")

    def test_stop_before_open_does_not_acquire_camera(self):
        worker, capture = self.worker()
        worker.stop_event.set()
        worker.run()
        self.assertEqual(capture.index, 0)
        self.assertFalse(worker.ready)

    def test_failed_backend_is_released_before_fallback(self):
        class Backend:
            def __init__(self, opened):
                self.opened, self.released = opened, False

            def isOpened(self):
                return self.opened

            def set(self, *args):
                pass

            def release(self):
                self.released = True

        failed, success = Backend(False), Backend(True)
        with patch("sys.platform", "win32"), patch("camera_engine.cv2.VideoCapture", side_effect=[failed, success]):
            self.assertIs(open_capture(0), success)
        self.assertTrue(failed.released)


if __name__ == "__main__":
    unittest.main()
