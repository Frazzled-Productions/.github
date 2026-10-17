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
    uses: Frazzled-Productions/.github/.github/workflows/ci.yml@main
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

```yaml
jobs:
  test:
    name: Engine and app tests
    uses: Frazzled-Productions/.github/.github/workflows/ios-ci.yml@main
    with:
      project: LoopYear.xcodeproj
      scheme: LoopYear
      engine-package: LoopYearEngine
    secrets: inherit
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
