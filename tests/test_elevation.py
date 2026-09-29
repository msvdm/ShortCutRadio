"""Running as administrator: how the program starts itself again."""

import os
import sys

import pytest

from src.core import elevation
from src.core.config import DEFAULTS


def test_off_by_default():
    assert DEFAULTS["run_as_admin"] is False


def test_the_built_app_starts_itself_with_the_options():
    exe = r"C:\Program Files\ShortCutRadio\shortcutradio.exe"
    assert elevation.command(["--hidden"], frozen=True, executable=exe) == (exe, "--hidden")
    assert elevation.command([], frozen=True, executable=exe) == (exe, "")


def test_from_source_it_is_python_and_the_script(tmp_path):
    script = tmp_path / "DEV Projects" / "shortcutradio.py"
    python = tmp_path / "python.exe"
    python.write_bytes(b"")
    file, params = elevation.command(["--replace"], frozen=False, executable=str(python),
                                     script=str(script))
    assert file == str(python)
    assert params == f'"{script}" --replace'       # a path with a space stays one argument


def test_from_source_it_prefers_no_console(tmp_path):
    python = tmp_path / "python.exe"
    for name in ("python.exe", "pythonw.exe"):
        (tmp_path / name).write_bytes(b"")
    file, _ = elevation.command([], frozen=False, executable=str(python),
                                script=str(tmp_path / "shortcutradio.py"))
    assert file == os.path.join(str(tmp_path), "pythonw.exe")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_it_can_tell_whether_it_is_elevated():
    assert elevation.is_elevated() in (True, False)


@pytest.mark.skipif(sys.platform == "win32", reason="elsewhere")
def test_elsewhere_it_never_is():
    assert not elevation.is_elevated()
    assert not elevation.relaunch([])
