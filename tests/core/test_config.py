import json
import os
import unittest

from pitstop.core.config import Config, ConfigError, load_config, parse_config, should_show_config_notice, update_config
from tests.helpers import TempLayoutTestCase


class ParseConfigTest(unittest.TestCase):
    def test_empty_object_gives_defaults(self):
        self.assertEqual(parse_config({}), Config(True, True, 200000, 50000, 10))

    def test_partial_object_overrides_only_given_keys(self):
        config = parse_config({"threshold_tokens": 60000})
        self.assertEqual((config.threshold_tokens, config.enabled), (60000, True))

    def test_unknown_keys_are_ignored(self):
        self.assertEqual(parse_config({"future": 1}), Config())

    def test_rejects_invalid_values(self):
        bad = [
            [],
            {"enabled": "yes"},
            {"notify": 1},
            {"threshold_tokens": 49999},
            {"threshold_tokens": 900001},
            {"threshold_tokens": True},
            {"threshold_tokens": 200000.0},
            {"retrigger_step_tokens": 9999},
            {"resume_window_minutes": 0},
            {"resume_window_minutes": 61},
        ]
        for raw in bad:
            with self.subTest(raw=raw):
                with self.assertRaises(ConfigError):
                    parse_config(raw)

    def test_accepts_range_limits(self):
        for raw in ({"threshold_tokens": 50000}, {"threshold_tokens": 900000}, {"retrigger_step_tokens": 10000},
                    {"resume_window_minutes": 1}, {"resume_window_minutes": 60}):
            with self.subTest(raw=raw):
                parse_config(raw)


class LoadConfigTest(TempLayoutTestCase):
    def write_config(self, text):
        self.layout.base.mkdir(parents=True, exist_ok=True)
        self.layout.config.write_text(text, encoding="utf-8")

    def test_missing_file_gives_defaults_without_error(self):
        self.assertEqual(load_config(self.layout), (Config(), None))

    def test_invalid_json_disables_pitstop_with_error(self):
        self.write_config("{nope")
        config, error = load_config(self.layout)
        self.assertFalse(config.enabled)
        self.assertIsNotNone(error)

    def test_invalid_value_disables_pitstop_with_error(self):
        self.write_config(json.dumps({"threshold_tokens": 1}))
        config, error = load_config(self.layout)
        self.assertFalse(config.enabled)
        self.assertIn("threshold_tokens", error)


class UpdateConfigTest(TempLayoutTestCase):
    def test_creates_file_with_full_config(self):
        config = update_config(self.layout, enabled=False)
        self.assertFalse(config.enabled)
        saved = json.loads(self.layout.config.read_text(encoding="utf-8"))
        self.assertEqual(saved["threshold_tokens"], 200000)

    def test_keeps_other_values(self):
        update_config(self.layout, threshold_tokens=60000)
        config = update_config(self.layout, notify=False)
        self.assertEqual((config.threshold_tokens, config.notify), (60000, False))

    def test_refuses_to_overwrite_invalid_file(self):
        self.layout.base.mkdir(parents=True)
        self.layout.config.write_text("{nope", encoding="utf-8")
        with self.assertRaises(ConfigError):
            update_config(self.layout, enabled=True)
        self.assertEqual(self.layout.config.read_text(encoding="utf-8"), "{nope")

    def test_rejects_invalid_change(self):
        with self.assertRaises(ConfigError):
            update_config(self.layout, threshold_tokens=10)


class ConfigNoticeTest(TempLayoutTestCase):
    def test_notice_shown_once_per_error_and_file_version(self):
        self.layout.base.mkdir(parents=True)
        self.layout.config.write_text("{nope", encoding="utf-8")
        self.assertTrue(should_show_config_notice(self.layout, "bad"))
        self.assertFalse(should_show_config_notice(self.layout, "bad"))
        later = self.layout.config.stat().st_mtime + 10
        os.utime(self.layout.config, (later, later))
        self.assertTrue(should_show_config_notice(self.layout, "bad"))
