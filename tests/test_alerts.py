import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from camera_alerts import AlertGate, SoundPlayer


def person(registered=False, visible_face=True):
    return SimpleNamespace(kind="human", embedding=object() if visible_face else None,
                           profile_id="known" if registered else None, label="Хүн")


def animal():
    return SimpleNamespace(kind="animal", embedding=None, profile_id=None, label="Арслан")


class AlertGateTests(unittest.TestCase):
    def test_unknown_face_notifies_after_three_consecutive_frames(self):
        gate = AlertGate()
        self.assertEqual(gate.observe([person()], 1), [])
        self.assertEqual(gate.observe([person()], 2), [])
        alert = gate.observe([person()], 3)[0]
        self.assertEqual(alert["kind"], "unknown_human")
        self.assertIn("Бүртгэлгүй хүн", alert["message"])

    def test_known_people_and_hidden_faces_do_not_trigger_unknown_alert(self):
        for obj in (person(registered=True), person(visible_face=False)):
            gate = AlertGate()
            for now in range(10):
                self.assertEqual(gate.observe([obj], now), [])

    def test_transient_detections_reset_the_streak(self):
        gate = AlertGate()
        gate.observe([animal()], 1)
        gate.observe([animal()], 2)
        gate.observe([], 3)
        self.assertEqual(gate.observe([animal()], 4), [])
        self.assertEqual(gate.observe([animal()], 5), [])
        self.assertEqual(gate.observe([animal()], 6)[0]["kind"], "animal")

    def test_animal_repeats_every_ten_seconds_and_human_every_thirty(self):
        gate = AlertGate(stable_frames=1)
        objects = [person(), animal()]
        self.assertEqual(len(gate.observe(objects, 100)), 2)
        self.assertEqual(gate.observe(objects, 109.9), [])
        self.assertEqual([a["kind"] for a in gate.observe(objects, 110)], ["animal"])
        self.assertEqual(gate.observe(objects, 119.9), [])
        self.assertEqual([a["kind"] for a in gate.observe(objects, 120)], ["animal"])
        self.assertEqual({a["kind"] for a in gate.observe(objects, 130)}, {"animal", "unknown_human"})

    def test_animal_alerts_continue_during_human_enrollment(self):
        gate = AlertGate(stable_frames=1)
        alerts = gate.observe([animal(), person()], 100, enrolling=True)
        self.assertEqual([a["kind"] for a in alerts], ["animal"])
        alerts = gate.observe([person()], 101, enrolling=False)
        self.assertEqual([a["kind"] for a in alerts], ["unknown_human"])

    def test_multiple_unknown_people_generate_one_notice_with_count(self):
        gate = AlertGate(stable_frames=1)
        alerts = gate.observe([person(), person(), person(registered=True)], 100)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["count"], 2)


class SoundPlayerTests(unittest.TestCase):
    def test_animal_sound_does_not_block_or_queue_overlapping_sounds(self):
        started, release = threading.Event(), threading.Event()
        fake_sound = Mock()

        def beep(*_args):
            started.set()
            release.wait(2)

        fake_sound.Beep.side_effect = beep
        with patch("camera_alerts.winsound", fake_sound):
            player = SoundPlayer()
            self.assertTrue(player.play("animal"))
            self.assertTrue(started.wait(2))
            self.assertTrue(player.play("animal"))
            release.set()
            player.thread.join(3)
            self.assertFalse(player.thread.is_alive())
            self.assertEqual(fake_sound.Beep.call_count, 2)
            player.close()

    def test_notification_sound_and_closed_player(self):
        fake_sound = Mock()
        with patch("camera_alerts.winsound", fake_sound):
            player = SoundPlayer()
            player.play("unknown_human")
            player.thread.join(2)
            self.assertEqual(fake_sound.MessageBeep.call_count, 1)
            player.close()
            player.play("animal")
            self.assertEqual(fake_sound.Beep.call_count, 0)

    def test_platform_without_winsound_requests_main_thread_bell(self):
        with patch("camera_alerts.winsound", None):
            self.assertFalse(SoundPlayer().play("animal"))


if __name__ == "__main__":
    unittest.main()
