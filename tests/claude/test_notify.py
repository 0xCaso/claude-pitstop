import sys
import unittest

from pitstop.claude.notify import notification_command, notify


class NotifyTest(unittest.TestCase):
    def test_text_is_passed_as_arguments_not_as_script(self):
        cmd = notification_command("pitstop", 'Ai box a 212K "quoted"')
        self.assertEqual(cmd[0], "/usr/bin/osascript")
        self.assertEqual(cmd[-2:], ['Ai box a 212K "quoted"', "pitstop"])
        self.assertNotIn("212K", " ".join(cmd[:-2]))

    def test_spawns_detached(self):
        calls = []
        notify("pitstop", "msg", spawn=lambda cmd, **kwargs: calls.append(kwargs))
        if sys.platform == "darwin":
            self.assertTrue(calls[0]["start_new_session"])
        else:
            self.assertEqual(calls, [])

    def test_spawn_errors_are_swallowed(self):
        def broken(cmd, **kwargs):
            raise OSError("no osascript")
        notify("pitstop", "msg", spawn=broken)
