"""Shape checks on the shared workflows that a lint does not make. Run: python3 -m unittest discover -s tools/ci -p 'test_*.py'

A required check's job must never carry an `if:` (a skipped job counts as passing a required check),
and the openspec CLI install must stay behind `install-openspec` (default false), so a self-hosted
caller that leaves the input unset installs nothing.
"""
import pathlib
import re
import unittest

WORKFLOWS = pathlib.Path(__file__).resolve().parents[2] / ".github/workflows"


class Shape(unittest.TestCase):
    def test_required_check_jobs_have_no_if(self):
        for name in ("openspec-required.yml", "context-budget.yml"):
            text = (WORKFLOWS / name).read_text(encoding="utf-8")
            jobs = text.split("\njobs:\n", 1)[1]
            self.assertIsNone(re.search(r"^    if:", jobs, re.M), name)

    def test_install_steps_are_gated_and_default_off(self):
        for name in ("openspec-archive.yml", "openspec-overlap.yml", "openspec-docs-check.yml"):
            text = (WORKFLOWS / name).read_text(encoding="utf-8")
            self.assertRegex(text, r"install-openspec:\n(?:        .*\n)*?        default: false\n", name)
            steps = re.findall(r"^      - (?:uses: actions/setup-node@.*|name: Install the openspec CLI)\n(.*)\n", text, re.M)
            self.assertEqual(len(steps), 2, name)
            for nxt in steps:
                self.assertEqual(nxt.strip(), "if: inputs.install-openspec", name)


if __name__ == "__main__":
    unittest.main()
