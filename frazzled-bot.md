# frazzled-bot - org automation App (setup spec)

The shared automation identity for the reusable orchestration workflows (auto-review posting review
comments, auto-release pushing the version commit/tag past branch protection, project-board
transitions). One GitHub App, installed org-wide, used by every repo's thin caller workflows. This is
the reusable version of Poké Memory's `poke-memory-bot`.

**This is a manual, one-time setup (owner action - App creation is shared GitHub state).** Once done,
the bot-dependent reusable workflows activate.

## Create the App
Org Settings → Developer settings → **GitHub Apps → New GitHub App**.
- **Name:** `frazzled-bot` (must be globally unique; if taken, `frazzled-productions-bot`).
- **Homepage URL:** the org URL (any valid URL).
- **Webhook:** **uncheck Active** (token-only use; no webhook needed).
- **Repository permissions:**
  - **Contents:** Read & write  - push release commits/tags.
  - **Issues:** Read & write  - comments, labels, project status.
  - **Pull requests:** Read & write  - review comments, status.
  - **Metadata:** Read (mandatory).
  - (Leave everything else None. Do **not** grant Administration or Workflows.)
- **Where can this App be installed:** Only on this account.
- Create, then **Install App** → the `Frazzled-Productions` org → **All repositories** (or select
  `sprue`, `poke-memory`, and add new repos as they appear).

## Capture the credentials
- Note the **App ID** (shown on the App's page).
- **Generate a private key** → downloads a `.pem`.

## Per-consuming-repo wiring (no org-level secrets on Free)
For each repo that runs the orchestration (`sprue`, `poke-memory`, …):
- Variable **`BOT_APP_ID`** = the App ID - `gh variable set BOT_APP_ID -R Frazzled-Productions/<repo> -b <id>`.
- Secret **`BOT_APP_PRIVATE_KEY`** = the `.pem` contents - `gh secret set BOT_APP_PRIVATE_KEY -R Frazzled-Productions/<repo> < frazzled-bot.private-key.pem`.

The reusable workflows mint a short-lived installation token at run time with
`actions/create-github-app-token@v1` from those two values - no long-lived PAT.

## Ruleset bypass (for repos with a protected default branch)
auto-release pushes the version commit/tag directly to a protected `main`, so the App must be a
**bypass actor** on that branch's ruleset (`actor_type: Integration`, `bypass_mode: always`). Add via
the repo's ruleset settings or the API (`PUT`, not partial `PATCH`).
**Gotcha:** transferring a repo keeps the ruleset rules but **drops bypass actors** - re-add the App's
bypass on every protected branch after any transfer.

## Status
- [ ] App created + installed org-wide
- [ ] `BOT_APP_ID` var + `BOT_APP_PRIVATE_KEY` secret set on `sprue`
- [ ] (later) same on `poke-memory` when it migrates to the reusable workflows
