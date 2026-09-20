"""Local process admission policy; mocks only, never starts Devin or a VM."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("fleet_linux_admission", Path(__file__).with_name("fleet.py"))
fleet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fleet)


class LinuxAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.os_patch = patch.object(fleet.os, "name", "posix")
        self.platform_patch = patch.object(fleet.sys, "platform", "linux")
        self.os_patch.start()
        self.platform_patch.start()
        self.addCleanup(self.os_patch.stop)
        self.addCleanup(self.platform_patch.stop)

    def test_no_devin_uses_read_only_all_process_name_listing(self):
        with patch.object(fleet, "run", return_value=" 1 systemd\n 42 python3\n 43 ps\n") as run:
            fleet.check_existing_sessions()
        run.assert_called_once_with(["ps", "-A", "-o", "pid=", "-o", "comm="], timeout=30)

    def test_exact_supported_process_names_rejected(self):
        for name in ("devin", "devin.exe", "DEVIN", "Devin.exe"):
            with self.subTest(name=name), patch.object(fleet, "run", return_value=f"1 systemd\n432 {name}\n"):
                with self.assertRaisesRegex(RuntimeError, "Existing Devin CLI"):
                    fleet.check_existing_sessions()

    def test_substrings_or_command_arguments_are_not_process_names(self):
        listing = "1 systemd\n2 devin-helper\n3 mydevin\n4 devin.exe.bak\n5 python devin.py\n"
        with patch.object(fleet, "run", return_value=listing):
            fleet.check_existing_sessions()

    def test_blank_and_malformed_listing_fail_closed(self):
        for listing in ("", " \n", "PID COMMAND\n", "12\n", "oops devin\n", "0 ps\n", "-1 ps\n", "１２ ps\n"):
            with self.subTest(listing=listing), patch.object(fleet, "run", return_value=listing):
                with self.assertRaisesRegex(RuntimeError, "Cannot verify"):
                    fleet.check_existing_sessions()

    def test_ps_failures_propagate_without_admission(self):
        for error in (FileNotFoundError("ps"), RuntimeError("ps failed"), subprocess.TimeoutExpired("ps", 30)):
            with self.subTest(error=error), patch.object(fleet, "run", side_effect=error):
                with self.assertRaises(type(error)):
                    fleet.check_existing_sessions()

    def test_unsupported_platform_fails_before_listing(self):
        for platform in ("darwin", "freebsd14", "unknown"):
            with self.subTest(platform=platform), patch.object(fleet.sys, "platform", platform), patch.object(fleet, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "unsupported"):
                    fleet.check_existing_sessions()
                run.assert_not_called()

    def test_windows_path_preserved(self):
        with patch.object(fleet.os, "name", "nt"), patch.object(fleet, "run", return_value='"devin.exe","123"\n') as run:
            with self.assertRaisesRegex(RuntimeError, "Existing Devin CLI"):
                fleet.check_existing_sessions()
        run.assert_called_once_with(["tasklist", "/FI", "IMAGENAME eq devin.exe", "/FO", "CSV", "/NH"])

    def test_windows_clear_listing_preserved(self):
        with patch.object(fleet.os, "name", "nt"), patch.object(fleet, "run", return_value="INFO: No tasks match\n"):
            fleet.check_existing_sessions()


if __name__ == "__main__":
    unittest.main()
