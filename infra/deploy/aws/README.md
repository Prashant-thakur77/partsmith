# Run the whole site on one AWS server

One x86 EC2 instance (t3.large, Ubuntu 24.04, 40 GB) with Docker. Caddy gets a free HTTPS certificate on its own. The public
default spends nothing on models: no keys on the server, `PROVIDER_MODE=replay`.

1. Open ports 80 and 443 to the world, and 22 only to your own address. Attach an Elastic IP.
2. Copy the repo to the server (a checkout or `git archive`).
3. In `infra/deploy/aws/`, create two files that are never committed:
   - `site.env`: `SITE_HOST=<host>`, `SITE_URL=https://<host>`, `REPO_URL=<repo url>`. Without your own domain, use
     `partsmith-<ip-with-dashes>.sslip.io` as the host.
   - `api.env`: start from `../api.env.example`; set `PARTSMITH_ADMIN_TOKEN` (`openssl rand -hex 24`), the public URLs and the
     MCP allowed hosts to that host.
4. `docker compose --env-file site.env up -d --build`, then open the site. The first boot seeds the registry from the committed samples.

Stop the instance when you no longer need it: `aws ec2 stop-instances --instance-ids <id>`. A stopped instance only costs its disk and the Elastic IP.
