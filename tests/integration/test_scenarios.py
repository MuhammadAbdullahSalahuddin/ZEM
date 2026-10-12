import subprocess
import sys


def _run(*extra):
    return subprocess.run(
        [sys.executable, "demo/run_scenarios.py", *extra],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


def test_scenarios_protected():
    r = _run()
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    assert sum(ln.startswith("PASS ") for ln in lines) == 6
    assert not any(ln.startswith("FAIL") for ln in lines)


def test_scenarios_unprotected_attacks_succeed():
    r = _run("--no-zem")  # proves the fake servers really are vulnerable
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("ATTACK SUCCEEDED") == 3
