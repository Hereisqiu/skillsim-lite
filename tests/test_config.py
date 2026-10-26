"""The .env search order: this project's folder first, then the parent folder for anything missing."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import config


class EnvLoadingTests(unittest.TestCase):
    def test_project_env_wins_and_parent_fills_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            project = parent / "skillsim"
            project.mkdir()
            (project / ".env").write_text("SKILLSIM_TEST_A=project\n")
            (parent / ".env").write_text("SKILLSIM_TEST_A=parent\nSKILLSIM_TEST_B=parent\n")
            with mock.patch.object(config, "ENV_CANDIDATES", [project / ".env", parent / ".env"]), \
                 mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("SKILLSIM_TEST_A", None)
                os.environ.pop("SKILLSIM_TEST_B", None)
                found = config.load_env()
                self.assertEqual(found, [project / ".env", parent / ".env"])
                self.assertEqual(os.environ["SKILLSIM_TEST_A"], "project")
                self.assertEqual(os.environ["SKILLSIM_TEST_B"], "parent")

    def test_parent_only_layout_used_by_graders(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            (parent / ".env").write_text("SKILLSIM_TEST_C=from-parent\n")
            with mock.patch.object(config, "ENV_CANDIDATES", [parent / "skillsim" / ".env", parent / ".env"]), \
                 mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("SKILLSIM_TEST_C", None)
                self.assertEqual(config.load_env(), [parent / ".env"])
                self.assertEqual(os.environ["SKILLSIM_TEST_C"], "from-parent")

    def test_course_path_is_pinned_to_gpt_6_luna(self):
        with mock.patch.object(config, "PROVIDER", "portkey"), mock.patch.dict(os.environ, {"PORTKEY_API_KEY": "x" * 20}):
            self.assertEqual(config.provider_settings()["model"], "gpt-6-luna")
