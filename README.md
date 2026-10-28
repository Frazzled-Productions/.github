# Frazzled-Productions/.github

The org's shared GitHub config + **reusable CI/automation workflows** - the workflow layer of the
[dev-toolkit-extraction-plan](https://github.com/Frazzled-Productions/ops/blob/main/dev-toolkit-extraction-plan.md)
(alongside the shared Claude skills and hooks in `ops/claude-home/` and `ops/standards/`; the old
`frazzled-claude` plugin is archived). `profile/README.md` is the public org page; everything else here is org-internal.

## Reusable workflows (`.github/workflows/`)

**Runner default (ops #345, from `v1.6.0`).** Every job that needs no Xcode (context budget, the five
OpenSpec workflows, test integrity, em-dash check, secret scan and the Lockfile gate) runs on the
caller's `runs-on` input when it passes one, otherwise on
`fromJSON(vars.LIGHT_RUNNER || '"ubuntu-latest"')`; their `runs-on` input defaults to `''`.
`LIGHT_RUNNER` is an organisation variable (`["light"]`, the two light runners on the Mac) visible to
private repositories only, and a reusable workflow reads `vars` as the caller's repository sees them:
a private caller that passes nothing lands on the light pool, a public one (website, poke-memory, this
repo) on GitHub-hosted `ubuntu-latest`. A repo-level `LIGHT_RUNNER` overrides it for one repo.
`em-dash-check` and `secret-scan` also still accept one raw label (`runs-on: self-hosted`). The Xcode
jobs (`ios-ci`, its Lockfile job, `ios-testflight`) keep `["self-hosted", "macOS", "ARM64"]`, the
app's own runner.

**Shared scripts (`tools/ios/`, `tools/ci/`).** The iOS workflows run `tools/ios/` (`ci-sim.sh` reap
and preboot, `retry-test-on-launch-failure.sh`, `with-build-lock.sh`, `lockfile_gate.py`,
`lockfile-check.sh`, generalised from koinori `origin/qa` 217b3f179), the secret scan
`tools/ci/gitleaks-install.sh` and the em-dash check `tools/ci/trailer.py`, each fetched from this
repository at the workflow's own commit, as the OpenSpec workflows do (below). Their tests run in
`self-test.yml` on hosted Ubuntu against stubs, never a real simulator.

**`@main` pins.** plan-bee's `em-dash-check` and koinori-web's `em-dash-check` and `secret-scan`
callers pin `@main`, so they get a merge here at once, before any tag moves.
- **`ci.yml`** - parameterised CI (`workflow_call`): install + optional lint / typecheck / test / build,
  configurable node version + working directory. Stack-agnostic (Next, Expo, plain Node).
  **Unused:** no repo calls it (checked 2026-10-17). Kept as a starting point for the npm repos;
  delete it if it is still uncalled at the next process review.

Consumer (thin caller in the app repo's `.github/workflows/`):
```yaml
jobs:
  ci:
    uses: Frazzled-Productions/.github/.github/workflows/ci.yml@v1
    with:
      node-version: '24'
      lint: npm run lint
      typecheck: npm run typecheck
      test: npm test
      build: npm run build
```
- **`em-dash-check.yml`** - the house-style job: fails when a PR or push adds a line containing an
  em dash, or when the PR body or a commit message the PR or push adds carries an AI-attribution
  trailer (koinori's pattern, any case; `tools/ci/trailer.py`). Diff-only, so old text never blocks new
  work. Inputs: `exclude` (git pathspec globs, one per line, em dashes only), `runs-on`. Callers add
  `edited` to their `pull_request` types so fixing the body re-runs it. Used by plan-bee, website,
  koinori-web and ops (checked 2026-10-23); the iOS apps call it too from ops #345 (`ios-ci.yml` no
  longer scans em dashes).
- **`ios-ci.yml`** - CI for the quick iOS apps (`workflow_call`), on the caller's self-hosted Mac
  runner: XcodeGen project check, then one step under the host build lock (ops
  `scripts/build-lock.sh`; a warning and no lock when it is missing) with the engine package tests and
  the app tests on the repo's own CI simulator (created if missing, erased and booted; named by
  `ci-simulator-name`, default the repo name in PascalCase plus `-CI-iPhone`), with
  `-test-timeouts-enabled YES` and one retry only on the simulator launch failure. A reap of the job's
  own workspace processes and CI simulator runs before and after. A light Lockfile gate decides
  whether the Lockfile job (every resolved package pinned, resolution leaves `Package.resolved`
  unchanged) needs the Mac. Inputs: `project`, `scheme`, `engine-package`, optional `simulator` (device
  model, `iPhone 18 Pro`), `ci-simulator-name`, `test-time-allowance` (120 s), `lockfile` (on),
  `runs-on`, `timeout-minutes` (100, which covers up to 60 minutes waiting for the lock).
  Used by Loop Year and Roast Conductor.
- **`ios-testflight.yml`** - archive and upload to TestFlight (`workflow_call`): the Release
  RevenueCat key copied in and removed afterwards, then the engine tests and the app's own
  `tools/release/testflight.sh` in one step under the host build lock, with a reap before and after.
  Job timeout default 130 minutes (lock wait plus archive).
  Inputs: `engine-package`, `secrets-xcconfig`, `asc-key-id`, `asc-issuer-id`, optional
  `release-script`, `runs-on`, `timeout-minutes`. Consumer snippets are in each file's header.
  The caller must run it only after CI passes on the same main commit (`workflow_run` on CI plus a
  gate job); see the header of `ios-testflight.yml`.
- **`test-integrity.yml`** - flags deleted test files, new skips (XCTSkip, withKnownIssue,
  `.disabled(`, `.skip(`, `.only(`, `test.fixme`), changed snapshot or visual baselines and changed
  thresholds, in one sticky PR comment, and fails unless the PR body has a `## Test changes` section
  naming each flagged file. Inputs: `warn-only` (pass with warnings, for a trial period), `runs-on`,
  `extra-test-pattern`, `extra-snapshot-pattern`, `pr-number` (check a bot PR from a
  `workflow_dispatch` run on its branch). OpenSpec files (`openspec/**`) never count as tests. The caller needs `pull-requests: write` and the
  `edited` PR event type, so fixing the PR body re-runs it. Snippet in the file header.
- **`secret-scan.yml`** - gitleaks over the history reachable from the caller's HEAD (`workflow_call`;
  a stale fetched ref on a self-hosted workspace is not scanned), pinned by version and a checksum per
  platform. Runs on Linux X64 and macOS ARM64 (the light runners), installed into the job's temp folder
  with no sudo. Lifted from koinori's own `secret-scan.yml`. Free alternative to GitHub secret scanning
  on private repos. Inputs: optional `gitleaks-version`, `gitleaks-sha256` (linux_x64),
  `gitleaks-sha256-darwin-arm64`, `runs-on`.

### OpenSpec tooling
Moved here from roast-conductor (owner decision 23 October 2026, `ops/research/openspec-trial-2026-10-21.md`,
"Review after Roast Conductor 1.0") so each app repo adopts OpenSpec with short callers. Every one of
these fetches its Python and shell tools from **this repository at the commit the workflow runs from**
(`job.workflow_sha`, the tag or SHA the caller pins; an annotated tag is resolved to its commit) into
the runner's temp folder, never from the
caller's tree, so a PR cannot change the guard it is judged by. The tools and their tests live in
`tools/openspec/` and `tools/ci/`; `self-test.yml` runs the tests on every PR here. Runner default: the
light route above (the light runners have git, gh, jq, python3 and the Homebrew `openspec` CLI); a
caller on GitHub-hosted runners passes `install-openspec: true`. Snippets are in each file's header.
- **`openspec-archive.yml`** - the archive bot. On the caller's push to the base branch (or "Run
  workflow") it archives each merged change with `openspec archive <name> --yes`, checks the result
  (`tools/openspec/archive.py`), pushes the archive branch, opens the PR, approves that PR's own held
  checks (`tools/openspec/approve_runs.py`: only the bot's own PR, from the archive branch into the base
  branch in the same repository, at the commit just pushed, with only plain files under `openspec/`
  changed, and only held `pull_request` runs the bot triggered) and turns on auto-merge. It first stops
  if the base branch's ruleset requires a check not in `required-contexts`. On the caller's `schedule`
  it instead runs the stuck job: an issue when an archive PR has been open longer than `stuck-minutes`.
  Failures open or comment on an issue labelled `openspec`, which opens with the real error lines; the
  failing step's log ends with the same lines as error annotations. When a later run archives the
  change, the bot comments on its own failure issue for it (linking the run and the archive PR) and
  closes it, once auto-merge is on (if a check then fails, the stuck job opens its own issue). Inputs: `required-contexts` (required, one
  per line), optional `runs-on`, `archive-branch` (default `openspec-archive`), `base-branch` (`main`),
  `stuck-minutes` (30), `install-openspec`. The caller job grants `actions: write`, `contents: write`,
  `pull-requests: write`, `issues: write`, `checks: read`; the repo needs "Allow GitHub Actions to
  create and approve pull requests".
- **`openspec-overlap.yml`** - on a PR: `openspec validate --strict` on each change it adds or edits,
  then fails if another open PR's delta MODIFIES, REMOVES or RENAMES the same requirement, or a target is
  no longer on the base branch (`tools/openspec/overlap.py`). Inputs: optional `runs-on`, `base-branch`,
  `install-openspec`.
  The caller job grants `contents: read`, `pull-requests: read`.
- **`openspec-changed-files.yml`** - output `docs-only`: `'true'` when every changed file is a plain file
  under `openspec/`, or Markdown at the root, in `docs/` or in `.claude/`, with deletions only under
  `openspec/` (`tools/ci/changed_files.py`; judged from git, renames split). Inputs: optional `runs-on`,
  `base-branch` (what a `workflow_dispatch` run is compared with).
- **`openspec-docs-check.yml`** - the quick real check a docs-only change gets instead of the full
  build: the archive checks (including `openspec validate --archived`: every archived change has all
  its tasks ticked), strict validation of active changes, the requirement length lint
  (`tools/openspec/requirement_length.py`: an ADDED or MODIFIED requirement in an active change's delta
  over OpenSpec's 500 characters fails, since `openspec validate --changes --strict` lets a MODIFIED one
  through and the archive after merge then fails, ops #313) and Markdown sanity. Before moving `v1` to a
  release that adds a check, run it on each caller (`openspec validate --archived` there) so no
  caller's `main` turns red. Inputs:
  `job-name` (so it can report under the caller's required check name), optional `runs-on`,
  `install-openspec`.
- **`openspec-required.yml`** - "OpenSpec required / OpenSpec required": a PR that changes more than
  docs must carry an OpenSpec change (`tools/openspec/required.py`). Docs-only PRs pass (the
  `changed_files.py` docs rule, plus the context budget file), and so do the archive bot's PRs, with no
  exemption by author or branch. Dependabot PRs pass when they only change dependency manifests, lock
  files or workflow files. Otherwise the PR must add or edit an active change in
  `openspec/changes/<name>/` whose head has a delta or `skip_specs: true`; with no `openspec/` at all it
  fails with "adopt OpenSpec first" and the kit's path (`ops/standards/openspec-adoption/README.md`).
  The one exception: the `no-spec` label added by `fraserbrookhouse` (from the PR's issue events; fixed
  in the tool, not an input) plus a `## No spec` section in the PR body, logged in the run and in one PR
  comment. No `if:` on the job, git, python3 and `gh` only. Inputs: optional `runs-on`, `budget-file`,
  `warn-only` (honoured only in this repo, for its self-test). The caller runs on `opened, synchronize, reopened, labeled,
  unlabeled` and grants `contents: read`, `pull-requests: write`, `issues: read`.
- **`context-budget.yml`** - "Context budget / Context budget": a ceiling on the instruction surface, a
  port of Koinori's `check-context-budget.sh` (`tools/ci/context_budget.py`). The budget file (input
  `budget-file`, default `.github/context-budget.txt`) holds `<path or GLOB:pattern or
  RULES_UNSCOPED><TAB><max lines>`; over budget fails, under only prints a note, a missing file fails
  with a seed of today's counts. On a PR, a raised entry needs an added `# <old> -> <new> on <date>:
  <reason>` line directly above it, and a removed one a `# removed <spec>: <reason>` line. No `if:` on
  the job; git and python3 only. Inputs: optional `runs-on`, `budget-file`.

`install-openspec` (default `false`): when `true`, the archive, overlap and docs-only check workflows
install `@fission-ai/openspec@1.14.3` from npm (`--ignore-scripts`) first, so a repo without a Mac
runner can run them with `runs-on: '"ubuntu-latest"'`. Repos with the self-hosted Mac leave it off.
The adoption kit, with every caller in a Mac and a GitHub-hosted variant and the rollout order (ship,
add the callers and the archive caller's `required-contexts`, see both report on a PR, then require
them), is `ops/standards/openspec-adoption/`.

A caller on `pull_request` runs the workflow file from the PR's own merge commit, so a PR could still
repoint its caller at another ref; the required checks and review catch that, as for any workflow
edit. The push and schedule callers (the archive bot) always run from the base branch.

Callers need no `secrets: inherit`: none of these workflows declares a secret.

## Command centre liveness (not reusable)
`command-centre-liveness.yml` runs here, not in callers, on GitHub-hosted Ubuntu (free, public repo). It
reads the repository variables the Mac writes: `CC_HEARTBEAT_AT` (the ops stall watcher, every run),
`CC_NOW_MD_AT` (the `now.md` job), `CC_MAC_AWAKE` (the ops Mac trigger, "awake since" and "last tick")
and `CC_TRIGGER_AT` (the trigger's last tick, relayed by the watcher). It opens one issue mentioning
Fraser when the watcher is over 30 minutes old while the Mac has been awake for 30 minutes, when the
trigger is silent while the watcher runs only on the backstop cron, or when any heartbeat is over 26
hours old; it edits the issue while the outage lasts and closes it when no rule holds. It never alarms
on a stale watcher while the Mac sleeps, and a variable never written is "not connected". Its cron asks
for every 3 hours, but GitHub delivers it about every 3 to 5 hours, so it is a coarse alarm. Logic and
tests: `tools/liveness/`. Runbook: `ops/runbooks/command-centre.md`.

## Self-test and releasing
`self-test.yml` runs actionlint and zizmor on every PR and on main (GitHub-hosted Ubuntu, never the
Mac runner: this repo is public), plus `test-integrity` on this repo's own PRs in warn-only mode, the
OpenSpec tools' unit tests (with the `openspec` CLI from npm at a pinned version), and the
`openspec-changed-files`, `openspec-overlap` (through `install-openspec`) and `openspec-required`
(warn-only, its "adopt OpenSpec first" result checked) workflows against this repo, proving the tools
fetch. `Context budget` checks this repo's own `.github/context-budget.txt`. From ops #345 it also
runs the `tools/ios` and `tools/ci` script tests with shellcheck, and calls `em-dash-check` with no
`runs-on`, a raw label and a JSON string, proving each routing form starts.

`main` is protected by a repo ruleset: changes land by PR only, and `actionlint and zizmor` plus
`Test integrity / Test integrity` must pass (admins can bypass only through a PR).

### RELEASING
Callers pin the moving major tag `@v1`, so a merge to main changes nothing in consumers until the
tag moves. `v1.0.0` (2026-10-17) is the first release.
1. Change on a branch; prove it on one caller by pointing that caller at the branch ref in a draft PR.
2. Merge here once self-test and the caller's run are green.
3. Tag the new main head `vX.Y.Z` (annotated), then move `v1` to its commit:
   `git tag -a v1.0.1 -m "..." && git tag -f v1 v1.0.1^{} && git push origin v1.0.1 && git push -f origin v1`.
   `v1` may be lightweight (as above) or annotated: for an annotated tag GitHub gives
   `job.workflow_sha` as the tag object, and the OpenSpec workflows' tools fetch resolves it to its
   commit (from v1.2.0; v1.1.0's fetch refuses it). Always point `v1` at the commit (`^{}`), never at
   another tag.
4. A breaking change (renamed or removed input, new required secret) gets a new major tag (`v2`) and
   a PR in each caller; `v1` stays where it is.

**`v1.6.0` (ops #345, light-runner-shared-ci).** Light jobs default to the light route; `ios-ci` and
`ios-testflight` gain the reap, the per-repo CI simulator, layered timeouts, one launch retry and the
host build lock; `ios-ci` gains the gated Lockfile job and loses its em-dash step; `secret-scan` runs on
Mac and Linux and scans HEAD only; `em-dash-check` gains the AI-attribution check. Every input change
is additive or a default, so it is a minor release. `v1` moves to it at the all-at-once landing with
the five companion changes, after the house-style job has run on each caller's latest PR.

```yaml
jobs:
  test:
    name: Engine and app tests
    uses: Frazzled-Productions/.github/.github/workflows/ios-ci.yml@v1
    with:
      project: LoopYear.xcodeproj
      scheme: LoopYear
      engine-package: LoopYearEngine
```

This repo is **public**, so private org repos can call its workflows without any Access setting
(GitHub applies the **Settings → Actions → Access** policy only to private and internal repos). If it
is ever made private, that setting must allow org repositories, or every consumer breaks.

## Not planned
Planned for porting from Poke Memory in June 2026, then dropped because no live repo needs them:
- `auto-review`, `auto-release`, `auto-issue` / `auto-pr`. The App spec they needed,
  [`frazzled-bot.md`](frazzled-bot.md), is parked with them.

## Shared templates
- **`PULL_REQUEST_TEMPLATE.md`** - the org default PR template (Evidence, Not done, `Refs #`). A repo's
  own template overrides it.
- **[`templates/dependabot.yml`](templates/dependabot.yml)** - the reference Dependabot config
  (7-day cooldown, grouped minor and patch, github-actions, `target-branch: qa` behind a qa gate).
  There is no inheritance, so each repo keeps a copy.

The org is on GitHub Team (`gh api orgs/Frazzled-Productions -q .plan.name`), but secrets and
ruleset bypasses are still wired per repo.
