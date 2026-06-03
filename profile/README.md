# Frazzled Productions

We build small, focused apps and turn the platform behind each one into a reusable asset the next app
inherits: build the product, then lift the platform out of it.

**Products**
- **Poké Memory** ([pokememory.com](https://pokememory.com)) - spaced repetition for learning Pokémon
  names and evolutions. Our first app and the reference implementation.
- **Sprue** - a Gunpla collection and backlog companion, native iOS. In progress.

**How we build.** Agent-driven development: issue-first, a plan before code, Claude subagents
implementing in parallel in isolated worktrees, an in-session review on every change, and a staging
branch that promotes to production. The reusable agents, commands, and conventions are extracted into a
shared toolkit so each new app starts from a forged toolchain rather than a blank page.

## Where things live (team)

The company source-of-truth is the **[ops](https://github.com/Frazzled-Productions/ops)** repo. Start
there:

- **[ops/README.md](https://github.com/Frazzled-Productions/ops/blob/main/README.md)** - the front
  door: how we work and where to find everything.
- **[ops/architecture.md](https://github.com/Frazzled-Productions/ops/blob/main/architecture.md)** -
  the map: every repo, what lives in it, and the layering model.
- **[ops/roadmap.md](https://github.com/Frazzled-Productions/ops/blob/main/roadmap.md)** - what is in
  flight and what is next.

**The repos:** `ops` (company source-of-truth) · `poke-memory` (product #1) · `sprue` (product #2) ·
`frazzled-claude` (the shared Claude agent toolkit) · `.github` (shared CI workflows + this profile) ·
`local-ai-trial` (local-AI research). The map in `ops/architecture.md` explains how they layer.
