"""Shape checks on the shared workflows that a lint does not make. Run: python3 -m unittest discover -s tools/ci -p 'test_*.py'

A required check's job must never carry an `if:` (a skipped job counts as passing a required check),
and every OpenSpec workflow installs the one pinned binary through tools/ci/openspec-install.sh, on
every runner, with no npm or Node step (ops #363). `install-openspec` stays accepted and does nothing.
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

    def test_openspec_install_is_the_pinned_script_on_every_runner(self):
        fetch = "      - name: Fetch the shared OpenSpec tools at this workflow's commit\n"
        step = (
            "      - name: Install the pinned openspec CLI\n"
            '        run: bash "$RUNNER_TEMP/frazzled-openspec-tools/tools/ci/openspec-install.sh" "$RUNNER_TEMP/openspec-bin"\n'
            "\n"
            "      - name: Show the openspec CLI on PATH\n"
            "        run: command -v openspec\n"
        )
        for name in ("openspec-archive.yml", "openspec-overlap.yml", "openspec-docs-check.yml"):
            text = (WORKFLOWS / name).read_text(encoding="utf-8")
            self.assertEqual(text.count(step), 1, name)
            self.assertNotIn("continue-on-error", text, name)
            self.assertLess(text.index(fetch), text.index(step), name)
            first_use = re.search(r"^\s+(?:run: )?(?:openspec (?:validate|archive)|python3 .*archive\.py)", text, re.M)
            if first_use:
                self.assertLess(text.index(step), first_use.start(), name)
            self.assertRegex(text, r"install-openspec:\n(?:        .*\n)*?        default: false\n", name)

    def test_no_npm_node_or_second_pin_for_openspec(self):
        for name in ("openspec-archive.yml", "openspec-overlap.yml", "openspec-docs-check.yml"):
            self.assertNotIn("setup-node", (WORKFLOWS / name).read_text(encoding="utf-8"), name)
        for path in WORKFLOWS.glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("@fission-ai/openspec", text, path.name)
            if path.name != "self-test.yml":  # Its pin check reads the release's SHA256SUMS.
                self.assertNotIn("Fission-AI/OpenSpec", text, path.name)
            self.assertNotIn("if: inputs.install-openspec", text, path.name)


    def test_simulated_archive_never_hides_the_overlap_step(self):
        # A change stuck on main makes "Simulated archive" red on every PR (ops #227); the overlap
        # report must still run, so the simulate step comes after it and runs unless cancelled.
        text = (WORKFLOWS / "openspec-overlap.yml").read_text(encoding="utf-8")
        names = re.findall(r"^      - name: (.*)$", text, re.M)
        self.assertEqual(names[-1], "Simulated archive", names)
        self.assertIn("      - name: Simulated archive\n        if: ${{ !cancelled() }}\n", text)


if __name__ == "__main__":
    unittest.main()
