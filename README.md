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
Private consumer repos need this repo's **Settings → Actions → Access** to allow org repositories.

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
