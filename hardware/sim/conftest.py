"""pytest wiring for the SPICE suite: designs, the `check` fixture and the results report.

Run:  python3 -m pytest hardware/sim -q            (writes hardware/sim/results/report.md and results.json)
      python3 -m pytest hardware/sim -q -n 4       (pytest-xdist: the report merges every worker's checks)

Every pytest process (the serial run, or each xdist worker) writes its checks to results/parts/<run id>/<worker>.json
when its session ends, then merges all part files of the run into report.md / results.json under a file lock. Part
files are only ever added during a run, so the last merge (the xdist controller, after every worker has finished, or
the last worker to finish if the run is interrupted) holds every check that ran. The merged list is in collection
order (the order of a serial run). A finished run removes its part directory; directories left by interrupted runs
are pruned after a day.
"""

from __future__ import annotations

import contextlib
import glob
import json
import numbers
import os
import shutil
import sys
import time
import uuid

import pytest

try:
    import fcntl
except ImportError:   # not POSIX: the merge still works, only without the lock between concurrent workers
    fcntl = None

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import spicelib  # noqa: E402

RESULTS = []
OUT = os.path.join(HERE, "results")
PARTS = os.path.join(OUT, "parts")
PARTS_MAX_AGE = 24 * 3600     # s: part directories of interrupted runs older than this are removed
_RUN_ID = pytest.StashKey[str]()


def _workerinput(config):
    return getattr(config, "workerinput", None)


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: long Monte Carlo / sweep runs (deselect with -m 'not slow')")
    config.addinivalue_line("markers", "fault: fault-injection tests that prove a check detects a broken design")
    wi = _workerinput(config)
    if wi is not None:   # xdist worker: the controller's run id (testrunuid if an older controller sent none)
        config.stash[_RUN_ID] = wi.get("sim_run_id") or wi["testrunuid"]
        return
    config.stash[_RUN_ID] = f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    _prune_parts()


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node):
    """xdist controller, before each worker starts: hand it this run's id, so all workers share one part directory."""
    node.workerinput["sim_run_id"] = node.config.stash[_RUN_ID]


@pytest.fixture(scope="session", autouse=True)
def _need_ngspice():
    if spicelib.NGSPICE is None:
        pytest.skip("ngspice is not installed")


@pytest.fixture
def main():
    return spicelib.Design("main")


@pytest.fixture
def base():
    return spicelib.Design("base")


@pytest.fixture
def check(request):
    """check(name, value, lo=None, hi=None, unit='', source='') records a measured value against its limits
    (datasheet / SPEC source) for the report, then asserts it."""
    def _check(name, value, lo=None, hi=None, unit="", source=""):
        ok = value is not None and (lo is None or value >= lo) and (hi is None or value <= hi)
        RESULTS.append(dict(test=request.node.nodeid, check=name, value=value, lo=lo, hi=hi, unit=unit,
                            source=source, ok=bool(ok)))
        assert ok, f"{name}: {value} {unit} outside [{lo}, {hi}] ({source})"
        return value
    return _check


# ------------------------------------------------------------------------------------------------ results report
def _prune_parts():
    now = time.time()
    for d in glob.glob(os.path.join(PARTS, "*")):
        try:
            if os.path.isdir(d) and now - os.path.getmtime(d) > PARTS_MAX_AGE:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def _json_default(o):
    """numpy scalars -> Python numbers (so a limit or value stays a number through the part file), else str."""
    if isinstance(o, numbers.Number) and hasattr(o, "item"):
        return o.item()
    return str(o)


def _write_atomic(path, text):
    tmp = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


@contextlib.contextmanager
def _locked(run_dir):
    with open(os.path.join(run_dir, ".lock"), "a") as f:
        if fcntl is not None:
            fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(f, fcntl.LOCK_UN)


def _read_parts(run_dir):
    merged, workers = [], []
    for path in sorted(glob.glob(os.path.join(run_dir, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                part = json.load(f)
        except (OSError, ValueError) as exc:   # never expected (parts are replaced atomically): say so, keep the rest
            print(f"\nconftest: cannot read results part {path}: {exc}", file=sys.stderr)
            continue
        workers.append(part["worker"])
        merged.extend(part["results"])
    merged.sort(key=lambda r: r["_order"])
    return [{k: v for k, v in r.items() if k != "_order"} for r in merged], workers


def _write_report(results, workers):
    os.makedirs(OUT, exist_ok=True)
    _write_atomic(os.path.join(OUT, "results.json"), json.dumps(results, indent=1, default=_json_default))
    lines = ["# SPICE suite results", "", "Generated by `python3 -m pytest hardware/sim`. Do not edit.", ""]
    if len(workers) > 1:
        lines += [f"Merged from {len(workers)} pytest-xdist workers ({', '.join(workers)}).", ""]
    lines += ["| Test | Check | Value | Limits | Source | |", "|---|---|---|---|---|---|"]
    for r in results:
        v = r["value"]
        val = spicelib.eng(v, r["unit"]) if isinstance(v, (int, float)) else str(v)
        lim = " … ".join(spicelib.eng(x, r["unit"]) if x is not None else "–" for x in (r["lo"], r["hi"]))
        lines.append(f"| `{r['test'].split('::')[-1]}` | {r['check']} | {val} | {lim} | {r['source']} | "
                     f"{'✅' if r['ok'] else '❌'} |")
    _write_atomic(os.path.join(OUT, "report.md"), "\n".join(lines) + "\n")


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    wi = _workerinput(config)
    worker = wi["workerid"] if wi is not None else "main"
    run_dir = os.path.join(PARTS, config.stash[_RUN_ID])
    if RESULTS:
        os.makedirs(run_dir, exist_ok=True)
        # collection index of each test (identical on every xdist worker), so the merged list is in serial order
        index = {item.nodeid: i for i, item in enumerate(session.items)}
        part = dict(worker=worker, results=[dict(r, _order=[index.get(r["test"], len(index)), k])
                                            for k, r in enumerate(RESULTS)])
        _write_atomic(os.path.join(run_dir, f"{worker}.json"), json.dumps(part, indent=1, default=_json_default))
    if not os.path.isdir(run_dir):
        return
    with _locked(run_dir):
        results, workers = _read_parts(run_dir)
        if results:
            _write_report(results, workers)
    # the serial process or the xdist controller ends last: once it has merged, the parts are no longer needed
    if wi is None and exitstatus != pytest.ExitCode.INTERRUPTED:
        shutil.rmtree(run_dir, ignore_errors=True)
