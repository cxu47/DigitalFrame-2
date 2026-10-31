# Phase 4 — Hong Kong host

Date: 2026-10-30  
Status: not started.  
Requires: [03-slideshow-site.md](03-slideshow-site.md) exit check.

## Outcome

The phase 3 process runs unchanged in a container. A short runbook says how to place that container on an Alibaba Cloud ECS instance in `cn-hongkong`. This phase builds the image locally. It does not create cloud resources, buy a domain, or put secrets into the image.

## Image

Add a `Dockerfile` at the repository root and a `.dockerignore` that excludes `.venv`, `.git`, `cache`, `secrets`, `.env`, and `users.yaml`.

- Base image `python:3.12-slim-bookworm`.
- Install uv from the official image copy or the Astral installer. Run `uv sync --locked --no-dev`.
- If `import pillow_heif` fails in the image, add the Debian `libheif` runtime package. Do not add it before that failure.
- Run as a non-root user.
- Command: `digitalframe serve`.
- The image contains code and dependencies only.

Runtime mounts, all required:

| Host path | In container | Mode |
| --- | --- | --- |
| `secrets/` including `oss.env` and `session.key` | `/app/secrets` | read-only, except `session.key` may be created on first run if the mount is writable |
| `users.yaml` | `/app/users.yaml` | read-only |
| cache directory | `/app/cache` | read-write |

`COOKIE_SECURE=true` in the server environment. `HOST=0.0.0.0` inside the container, published only through the TLS proxy below.

## Runbook

Add `deploy/hong-kong.md`. It is the operator document. Keep it to these steps.

1. Use the existing bucket in `cn-hongkong`. Leave it private. Do not turn on static website hosting and do not add a public bucket policy.
2. Create a RAM user used only by this app. Attach only the policy below, with the real bucket name substituted. Do not use the account root key.
3. Create an ECS instance in `cn-hongkong`, about 2 vCPU and 4 GB memory, with a data disk for the cache. Ubuntu 24.04 is enough. Install Docker.
4. Security group: inbound TCP 443 from the internet, and SSH only from the administrator's address. No public port 8000.
5. Point a domain name at the instance. Terminate TLS on the VM with Caddy, which obtains a certificate for that name and reverse-proxies to `127.0.0.1:8000`. A bare IP is not the deployment target.
6. In `secrets/oss.env` on the VM, set `OSS_ENDPOINT=https://oss-cn-hongkong-internal.aliyuncs.com` so listing and downloads use the region-internal network.
7. Start the container with the mounts above and a restart policy. Confirm the login page over HTTPS, then confirm a photo plays.

Hong Kong hosting does not require ICP filing. A mainland-region VM would. The runbook does not offer that option.

The manual cloud work stays manual. Phase 4 is finished when the image builds, not when the VM exists.

## RAM policy

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["oss:ListObjects"],
      "Resource": ["acs:oss:*:*:BUCKET_NAME"]
    },
    {
      "Effect": "Allow",
      "Action": ["oss:GetObject"],
      "Resource": ["acs:oss:*:*:BUCKET_NAME/photos/*"]
    }
  ]
}
```

`BUCKET_NAME` is the only substitution. The policy grants neither `PutObject` nor `DeleteObject`.

## Exit check

From a clean tree, `docker build -t digitalframe-2 .` finishes. `docker run` with fixture mounts and no OSS credentials starts, serves the login page, and refuses `/media` without a session. No cloud API call is required for this check.
