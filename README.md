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
- **`secret-scan.yml`** - gitleaks over the caller's full history (`workflow_call`), pinned by version
  and checksum. Lifted from koinori's own `secret-scan.yml`. Free alternative to GitHub secret
  scanning on private repos. Inputs: optional `gitleaks-version`, `gitleaks-sha256`, `runs-on`.

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
