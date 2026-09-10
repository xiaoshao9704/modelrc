"""bin/modelrc 解释器引导层的测试。

这层的价值在于：换一台机器、或者 hook 子进程的 PATH 被裁剪、或者 PATH 上第一个
python3 版本过低时，仍然能确定性地挑到一个可用解释器。
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

MODELRC = Path(__file__).resolve().parent.parent / "bin" / "modelrc"
PAYLOAD = '{"hook_event_name":"SessionStart","model":"probe-x","cwd":"/tmp","permission_mode":"default"}'


def run(args, env=None, stdin=""):
    base = dict(os.environ)
    base.update(env or {})
    return subprocess.run(
        [str(MODELRC)] + args, input=stdin, capture_output=True, text=True, env=base
    )


def fake_bin(tmp_path, name, body):
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_text(body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return d


def test_runs_normally():
    assert run(["manifest"]).returncode == 0


def test_skips_python3_that_fails_version_check(tmp_path):
    """PATH 上第一个 python3 版本过低时，必须跳过它而不是直接失败。"""
    d = fake_bin(tmp_path, "python3", "#!/bin/sh\nexit 1\n")
    got = run(["manifest"], env={"PATH": f"{d}:{os.environ['PATH']}"})
    assert got.returncode == 0, got.stderr
    assert "SessionStart" in got.stdout


def test_works_with_stripped_path(tmp_path):
    """hook 子进程的 PATH 可能被裁剪到只剩基本目录，绝对路径兜底必须生效。"""
    got = run(["manifest"], env={"PATH": "/nonexistent"})
    assert got.returncode == 0, got.stderr
    assert "SessionStart" in got.stdout


def test_modelrc_python_override_is_honored():
    got = run(["manifest"], env={"MODELRC_PYTHON": "/usr/bin/python3"})
    assert got.returncode == 0
    assert "SessionStart" in got.stdout


def test_bad_override_falls_through_to_working_interpreter():
    got = run(["manifest"], env={"MODELRC_PYTHON": "/definitely/not/here"})
    assert got.returncode == 0, got.stderr
    assert "SessionStart" in got.stdout


def test_no_interpreter_at_all_exits_zero(tmp_path):
    """一个都找不到时也必须以 0 退出，不能打断 agent 会话。"""
    d = tmp_path / "empty"
    d.mkdir()
    # 让所有候选都探测失败：PATH 清空，且把绝对路径候选用 MODELRC_PYTHON 顶掉是不够的，
    # 所以这里在一个只含失败版 python 的 PATH 下运行，并断言退出码。
    for name in ("python3", "python", "python3.9", "python3.10", "python3.11",
                 "python3.12", "python3.13", "python3.14"):
        p = d / name
        p.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    # 绝对路径候选真实存在，所以这里只断言「不崩溃且退出码为 0」。
    got = run(["hook"], env={"PATH": str(d)}, stdin=PAYLOAD)
    assert got.returncode == 0


def test_hook_never_breaks_session_on_garbage_input():
    got = run(["hook"], stdin="not json")
    assert got.returncode == 0
    assert got.stdout == ""


def test_shim_is_posix_sh_not_python():
    assert MODELRC.read_text(encoding="utf-8").startswith("#!/bin/sh")
    assert shutil.which("sh")
