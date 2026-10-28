"""Structure of the shared iOS workflows (ops #345, light-runner-shared-ci design D1 and D5).

Run: python3 -m unittest discover -s tools/ios -p 'test_*.py' (needs PyYAML, which the hosted Ubuntu
runner's python3 has).

The script tests stub Xcode, so nothing else notices when a workflow edit moves an Xcode job to the
light route, drops the `if: always()` from the reap after, or takes a build out of the host build
lock (all three slipped through the 28 October 2026 final review with every self-test green). This
reads ios-ci.yml and ios-testflight.yml and checks:
  - the Xcode jobs run on the caller's runner, by default ["self-hosted", "macOS", "ARM64"];
  - a reap runs before the first Xcode step, and an `if: always()` reap after the last;
  - every step that runs xcodebuild, swift test, the lockfile check or the release (archive) script
    runs it through with-build-lock.sh;
  - each locked step's timeout is below the job's and at least 60 (the lock wait) plus its work;
  - the Lockfile gate job is light.
Each check is also proven against a mutated copy, so a check that stops looking fails here.
"""
import copy
import json
import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

XCODE_RUNNER = ["self-hosted", "macOS", "ARM64"]
CALLER_RUNNER = "${{ fromJSON(inputs.runs-on) }}"
LIGHT_RUNNER = "${{ fromJSON(vars.LIGHT_RUNNER || '\"ubuntu-latest\"') }}"
LOCK_WAIT = 60
# Minutes of real work in each locked step beyond the lock wait (design D5: 90, 75 and 120 minutes).
XCODE_JOBS = {
    ("ios-ci.yml", "test"): 30,
    ("ios-ci.yml", "lockfile"): 15,
    ("ios-testflight.yml", "upload"): 60,
}
LIGHT_JOBS = {("ios-ci.yml", "lockfile-gate")}
XCODE_WORK = re.compile(r"xcodebuild|swift test|lockfile-check\.sh|RELEASE_SCRIPT")
REAP = re.compile(r"ci-sim\.sh\"? reap")


def load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def inputs_of(wf):
    # PyYAML reads the `on` key as True.
    on = wf.get("on", wf.get(True)) or {}
    return (on.get("workflow_call") or {}).get("inputs") or {}


def minutes(value, inputs):
    if isinstance(value, int):
        return value
    m = re.fullmatch(r"\$\{\{\s*inputs\.([\w-]+)\s*\}\}", str(value).strip())
    return int(inputs[m.group(1)]["default"]) if m else None


def violations(name, wf):
    """Every structure rule `wf` (the parsed workflow called `name`) breaks."""
    out = []
    inputs = inputs_of(wf)
    jobs = wf.get("jobs") or {}
    for (wf_name, job_id), work in XCODE_JOBS.items():
        if wf_name != name:
            continue
        job = jobs.get(job_id)
        if job is None:
            out.append(f"{name} {job_id}: missing")
            continue
        where = f"{name} {job_id}"
        if job.get("runs-on") != CALLER_RUNNER:
            out.append(f"{where}: runs-on is {job.get('runs-on')!r}, not the caller's Xcode runner")
        else:
            default = (inputs.get("runs-on") or {}).get("default")
            if json.loads(default or "null") != XCODE_RUNNER:
                out.append(f"{where}: runs-on input defaults to {default!r}, not {XCODE_RUNNER}")
        steps = job.get("steps") or []
        runs = [str(s.get("run") or "") for s in steps]
        xcode = [i for i, r in enumerate(runs) if XCODE_WORK.search(r)]
        reaps = [i for i, r in enumerate(runs) if REAP.search(r)]
        if not xcode:
            out.append(f"{where}: no Xcode step found")
            continue
        if not any(i < xcode[0] and "if" not in steps[i] for i in reaps):
            out.append(f"{where}: no reap before the first Xcode step")
        if not any(i > xcode[-1] and str(steps[i].get("if", "")).strip() == "always()" for i in reaps):
            out.append(f"{where}: no `if: always()` reap after the last Xcode step")
        job_timeout = minutes(job.get("timeout-minutes"), inputs)
        for i in xcode:
            step = steps[i]
            label = f"{where} step {step.get('name', i)!r}"
            lock = runs[i].find("with-build-lock.sh")
            if lock < 0 or lock > XCODE_WORK.search(runs[i]).start():
                out.append(f"{label}: runs Xcode work outside with-build-lock.sh")
            step_timeout = minutes(step.get("timeout-minutes"), inputs)
            if step_timeout is None or job_timeout is None:
                out.append(f"{label}: step or job has no timeout")
                continue
            if step_timeout >= job_timeout:
                out.append(f"{label}: step timeout {step_timeout} is not below the job's {job_timeout}")
            if step_timeout < LOCK_WAIT + work:
                out.append(f"{label}: step timeout {step_timeout} is under {LOCK_WAIT} (lock wait) + {work} (work)")
    for wf_name, job_id in LIGHT_JOBS:
        if wf_name == name:
            job = jobs.get(job_id) or {}
            if job.get("runs-on") != LIGHT_RUNNER:
                out.append(f"{name} {job_id}: runs-on is {job.get('runs-on')!r}, not the light route")
    return out


def step_index(job, pattern, **match):
    for i, s in enumerate(job["steps"]):
        if re.search(pattern, str(s.get("run") or "")) and all(s.get(k) == v for k, v in match.items()):
            return i
    raise AssertionError(f"no step matching {pattern!r} {match}")


class RealWorkflows(unittest.TestCase):
    def test_ios_ci(self):
        self.assertEqual(violations("ios-ci.yml", load("ios-ci.yml")), [])

    def test_ios_testflight(self):
        self.assertEqual(violations("ios-testflight.yml", load("ios-testflight.yml")), [])


class Mutations(unittest.TestCase):
    """Each check catches the edit it exists for."""

    def setUp(self):
        self.ci = copy.deepcopy(load("ios-ci.yml"))
        self.tf = copy.deepcopy(load("ios-testflight.yml"))

    def assertCaught(self, name, wf, text):
        found = violations(name, wf)
        self.assertTrue(any(text in v for v in found), f"expected {text!r} in {found}")

    def test_lockfile_job_on_the_light_route(self):
        self.ci["jobs"]["lockfile"]["runs-on"] = LIGHT_RUNNER
        self.assertCaught("ios-ci.yml", self.ci, "lockfile: runs-on is")

    def test_xcode_default_runner_changed(self):
        self.ci[True]["workflow_call"]["inputs"]["runs-on"]["default"] = '["light"]'
        self.assertCaught("ios-ci.yml", self.ci, "runs-on input defaults to")

    def test_reap_after_without_always(self):
        job = self.ci["jobs"]["test"]
        del job["steps"][step_index(job, REAP.pattern, **{"if": "always()"})]["if"]
        self.assertCaught("ios-ci.yml", self.ci, "test: no `if: always()` reap after")

    def test_reap_before_removed(self):
        job = self.tf["jobs"]["upload"]
        del job["steps"][step_index(job, REAP.pattern)]
        self.assertCaught("ios-testflight.yml", self.tf, "upload: no reap before")

    def test_lock_wrapper_removed(self):
        job = self.ci["jobs"]["test"]
        step = job["steps"][step_index(job, "with-build-lock")]
        step["run"] = "swift test --package-path \"$ENGINE_PACKAGE\"\nxcodebuild test -project \"$PROJECT\"\n"
        self.assertCaught("ios-ci.yml", self.ci, "runs Xcode work outside with-build-lock.sh")

    def test_archive_outside_the_lock(self):
        job = self.tf["jobs"]["upload"]
        job["steps"].insert(step_index(job, "with-build-lock"), {"name": "Archive", "run": 'zsh "$RELEASE_SCRIPT"',
                                                                 "timeout-minutes": 120})
        self.assertCaught("ios-testflight.yml", self.tf, "'Archive': runs Xcode work outside with-build-lock.sh")

    def test_step_timeout_not_below_the_job(self):
        job = self.ci["jobs"]["lockfile"]
        job["steps"][step_index(job, "with-build-lock")]["timeout-minutes"] = 85
        self.assertCaught("ios-ci.yml", self.ci, "is not below the job's 85")

    def test_step_timeout_leaves_no_room_for_work(self):
        job = self.tf["jobs"]["upload"]
        job["steps"][step_index(job, "with-build-lock")]["timeout-minutes"] = 90
        self.assertCaught("ios-testflight.yml", self.tf, "is under 60 (lock wait) + 60 (work)")

    def test_lockfile_gate_on_the_xcode_runner(self):
        self.ci["jobs"]["lockfile-gate"]["runs-on"] = CALLER_RUNNER
        self.assertCaught("ios-ci.yml", self.ci, "lockfile-gate: runs-on is")


if __name__ == "__main__":
    unittest.main()
