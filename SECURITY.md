# Security

## Reporting a problem

Please report vulnerabilities privately through GitHub: **Security → Report a vulnerability** on this repository. Do not open
a public issue. Say what you found and how to reproduce it. You can expect a reply within a few days.

These matter most:

- Escaping the sandbox that runs model-written CadQuery (`services/geom_worker`).
- Getting a part marked verified, or downloading one, without passing the verifier and the export gate
  (`services/verifier`, `services/registry/gate.py`).
- Exposing an API key, or spending past the daily cap (`services/agent/providers`).
- Reaching an admin route without the token (`services/api`, `services/admin`).

## How the project limits risk

- Model-written CAD runs in a child process with an AST allowlist, CPU, memory and file-size limits, no network and a
  throwaway working directory.
- API keys stay on the server, and live voice is relayed by the API. The secret scan runs as a pre-commit hook and through
  `make gitleaks`.
- The public demo runs in replay mode with no model keys. The API refuses to start without an admin token.
- `PARTSMITH_DAILY_USD_CAP` stops live model calls for the rest of the UTC day once the cap is reached.

## Printed parts

Do not use a part from this project where failure could hurt someone. The project refuses medical, vehicle-safety and weapon
parts by design, and a passed check means the model matches the photos, not that the part is safe for a given use.
