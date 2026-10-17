# Frazzled-Productions/.github

The org's shared GitHub config + **reusable CI/automation workflows** - the workflow layer of the
[dev-toolkit-extraction-plan](https://github.com/Frazzled-Productions/ops/blob/main/dev-toolkit-extraction-plan.md)
(alongside the [`frazzled-claude`](https://github.com/Frazzled-Productions/frazzled-claude) plugin and
`ops/standards/`). `profile/README.md` is the public org page; everything else here is org-internal.

## Reusable workflows (`.github/workflows/`)
- **`ci.yml`** - parameterised CI (`workflow_call`): install + optional lint / typecheck / test / build,
  configurable node version + working directory. Stack-agnostic (Next, Expo, plain Node). **(live)**

Consumer (thin caller in the app repo's `.github/workflows/`):
```yaml
jobs:
  ci:
    uses: Frazzled-Productions/.github/.github/workflows/ci.yml@main
    with:
      node-version: '24'
      lint: npm run lint
      typecheck: npm run typecheck
      test: npm test
      build: npm run build
```
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
  `extra-test-pattern`, `extra-snapshot-pattern`. The caller needs `pull-requests: write` and the
  `edited` PR event type, so fixing the PR body re-runs it. Snippet in the file header.

Callers need no `secrets: inherit`: none of these workflows declares a secret.

## Self-test and releasing
`self-test.yml` runs actionlint and zizmor on every PR and on main (GitHub-hosted Ubuntu, never the
Mac runner: this repo is public), plus `test-integrity` on this repo's own PRs in warn-only mode.

Callers currently use `@main`, so a merge here changes CI and TestFlight in every consumer at once.
Planned release flow (needs the owner's approval, because tags are shared state):
1. Change on a branch; prove it on one caller by pointing that caller at the branch ref in a draft PR.
2. Merge here once self-test and the caller's run are green.
3. Tag `vX.Y.Z` and move the major tag (`v1`) to it; callers pin `@v1`.

```yaml
jobs:
  test:
    name: Engine and app tests
    uses: Frazzled-Productions/.github/.github/workflows/ios-ci.yml@main
    with:
      project: LoopYear.xcodeproj
      scheme: LoopYear
      engine-package: LoopYearEngine
```

This repo is **public**, so private org repos can call its workflows without any Access setting
(GitHub applies the **Settings → Actions → Access** policy only to private and internal repos). If it
is ever made private, that setting must allow org repositories, or every consumer breaks.

## Automation identity
- **[`frazzled-bot.md`](frazzled-bot.md)** - setup spec for the org automation App (manual, one-time
  owner action). Required before the bot-dependent workflows below.

## To port (pulled through as consumers need them; bot-dependent → after `frazzled-bot` exists)
- `auto-review` - runs the `code-reviewer` agent on PRs, posts an idempotent punch list.
- `auto-release` - changelog-fragment assembly + SemVer bump + tag (needs the bot's ruleset bypass).
- `auto-issue` / `auto-pr` - the command-driven plan→implement→fix orchestration (the heaviest;
  generalise from Poké Memory once the simpler pieces are proven on Sprue).

Org-level secrets + rulesets need GitHub Team; the org is on Free ([ops ADR 0005]), so wiring is
per-repo (secrets, ruleset bypass) by design.
