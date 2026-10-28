# Docs index

| Doc | What it covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Pipeline and runtime diagrams, side paths and the check that decides each, contracts, frames, module interfaces |
| [API.md](API.md) | REST + SSE endpoints under `/api/v1`, with request and response shapes |
| [DECISIONS.md](DECISIONS.md) | Architecture decision log, one paragraph per decision, newest last |
| [QUALITY.md](QUALITY.md) | Self-review scorecard per area, with the evidence behind each score |
| [PROGRESS.md](PROGRESS.md) | Build log: what was done, the command that proves it, what is next |
| [HANDOFF.md](HANDOFF.md) | What only the owner can do: keys, real photos, deploy, video, submission |
| [FAQ_ANSWERS.md](FAQ_ANSWERS.md) | Answers to hackathon questions the participant guide does not cover |
| [links.json](links.json) | URLs for the README link row (live site, video, judges page, sample); empty means "(coming)" |
| [../eval/REPRODUCE.md](../eval/REPRODUCE.md) | How every bench number is produced, and the commands to reproduce it |

Elsewhere in the repo:

| Doc | What it covers |
|---|---|
| [../services/metrology/README.md](../services/metrology/README.md) | Photo → millimetres: mats, capture gate, segmentation, feature fits |
| [../services/mcp/README.md](../services/mcp/README.md) | The MCP server: tools, transports, client setup |
| [../infra/modal/README.md](../infra/modal/README.md) | Self-hosting Muse Glimmer and SAM 3 open weights on Modal |
| [../infra/deploy/README.md](../infra/deploy/README.md) | Deploying the replay-mode public demo |

The README's generated blocks (status line, headline numbers, Meta model table, results, built-during-the-hackathon table)
are written by `uv run python -m tools.readme`; never edit them by hand.
