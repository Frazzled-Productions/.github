# Frazzled-Productions/.github

The org's shared GitHub config + **reusable CI/automation workflows** - the workflow layer of the
[dev-toolkit-extraction-plan](https://github.com/Frazzled-Productions/ops/blob/main/dev-toolkit-extraction-plan.md)
(alongside the [`frazzled-claude`](https://github.com/Frazzled-Productions/frazzled-claude) plugin and
`ops/standards/`). `profile/README.md` is the public org page; everything else here is org-internal.

## Reusable workflows (`.github/workflows/`)
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
- **`em-dash-check.yml`** - fails when a PR or push adds a line containing an em dash (house style).
  Diff-only, so old text never blocks new work. Input: `exclude` (git pathspec globs, one per line).
  Used by plan-bee, website, koinori-web and ops; the iOS apps get the check from `ios-ci.yml`.
- **`ios-ci.yml`** - CI for the quick iOS apps (`workflow_call`): XcodeGen project check, no em
  dashes, engine package tests, app tests on the simulator, on the caller's self-hosted Mac runner.
  Inputs: `project`, `scheme`, `engine-package`, optional `simulator`, `runs-on`, `timeout-minutes`.
  Used by Loop Year and Roast Conductor.
- **`ios-testflight.yml`** - archive and upload to TestFlight (`workflow_call`): engine tests, the
  Release RevenueCat key copied in and removed afterwards, the app's own `tools/release/testflight.sh`.
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
- **`secret-scan.yml`** - gitleaks over the caller's full history (`workflow_call`), pinned by version
  and checksum. Lifted from koinori's own `secret-scan.yml`. Free alternative to GitHub secret
  scanning on private repos. Inputs: optional `gitleaks-version`, `gitleaks-sha256`, `runs-on`.

Callers need no `secrets: inherit`: none of these workflows declares a secret.

## Self-test and releasing
`self-test.yml` runs actionlint and zizmor on every PR and on main (GitHub-hosted Ubuntu, never the
Mac runner: this repo is public), plus `test-integrity` on this repo's own PRs in warn-only mode.

`main` is protected by a repo ruleset: changes land by PR only, and `actionlint and zizmor` plus
`Test integrity / Test integrity` must pass (admins can bypass only through a PR).

### RELEASING
Callers pin the moving major tag `@v1`, so a merge to main changes nothing in consumers until the
tag moves. `v1.0.0` (2026-10-17) is the first release.
1. Change on a branch; prove it on one caller by pointing that caller at the branch ref in a draft PR.
2. Merge here once self-test and the caller's run are green.
3. Tag the new main head `vX.Y.Z` (annotated), then move `v1` to it:
   `git tag -a v1.0.1 -m "..." && git tag -f -a v1 -m "v1: now v1.0.1" v1.0.1 && git push origin v1.0.1 && git push -f origin v1`.
4. A breaking change (renamed or removed input, new required secret) gets a new major tag (`v2`) and
   a PR in each caller; `v1` stays where it is.

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
