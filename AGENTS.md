# AGENTS.md - frazzled-dotgithub (org .github)

Layer 1 company-shared repo: the org's shared GitHub config and reusable CI/automation workflows.
[README.md](README.md) documents each workflow and its consumer snippet. `profile/README.md` is the
**public** org page; everything else is org-internal.

## Where to store information
Defaults per `ops/standards/where-things-live.md` and `ops/KNOWLEDGE.md`. Reusable workflows live
here; the process rules they enforce live in `ops/standards/process.md` - reference, never copy.

## Conventions
Company standards: `ops/standards/` (British English, no em dashes, commits in the maker's name).
Repo-local: workflows are `workflow_call` reusable and stack-agnostic; breaking a workflow breaks
every consumer repo, so treat changes as cross-repo changes. Anything in `profile/` is public copy;
check it reads correctly to outsiders. Do not push without asking (not on the auto-push list).
