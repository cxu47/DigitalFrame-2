# Phase 5 — Function Compute

Date: 2026-10-30  
Status: plan only. Do not start until this plan is accepted.  
Requires: [04-hong-kong-host.md](04-hong-kong-host.md) stays in place. The ECS runbook is not removed.  
Next: none. Implementation waits for an explicit go-ahead.

## Evaluation

Alibaba Cloud Function Compute in `cn-hongkong` fits the new hosting goal: a visit wakes the app, and idle time does not pay for a virtual machine. The product name is Function Compute. A custom container is the right shape, because phase 4 already builds `digitalframe-2`.

The current process cannot be moved unchanged. Three things assume a machine that stays on:

| Current behavior | Why it breaks at zero instances | Replacement |
| --- | --- | --- |
| Sessions live in process memory | The next visit can start a new instance that has never seen the cookie | A signed cookie that carries the view by itself |
| A background thread syncs forever | Nothing runs while the function is frozen | Sync when a visit finds the catalog stale |
| Derivatives sit on a local disk | That disk disappears with the instance | Store derivatives in the same private bucket, under a separate prefix |

What stays: the photo rules, passcode file, canvas playback, focus blackout, translations, and the phase 4 ECS path. Local `digitalframe serve` and the ECS container keep working. Function Compute is a second way to run the same app.

Idle cost stays small only if these are refused:

- A minimum instance count above zero. That is a virtual machine again.
- Provisioned instances.
- A NAS disk. It bills every month whether or not anyone visits.
- A timer that wakes the function on a schedule. Sync happens on a visit instead.

Standing cost is then OSS storage for the original photos and the derivatives, plus the container image in a registry in `cn-hongkong`. Compute is billed for the seconds a visit keeps an instance awake, including a short platform grace period after the last request. The first visit after a quiet stretch waits through a cold start, often several seconds, before the login page appears.

Hong Kong Function Compute does not need ICP filing. Viewers in mainland China use the same kind of path as the Hong Kong ECS plan: HTTPS to Hong Kong, then the function reads the private bucket. The browser still never receives an OSS URL.

## Order inside this phase

Each step keeps the local app runnable. Do not begin the cloud setup until the local exit check of the previous step passes.

### 1. Stateless session

The cookie is already signed with the session key. The view is not in the cookie. Folder, months, seconds per photo, and expiry live only in the `Sessions` object.

- Put that view into the signed cookie. Any instance with the same key can read it.
- Read `SESSION_KEY` from the environment when it is set. Keep creating `secrets/session.key` for local and ECS runs.
- Leave the login limiter in memory. A cold start resets it. That is acceptable for a family passcode.
- Tests must show a cookie issued by one app object still authorizes a second app object that shares only the key.

Exit check: pytest passes, and a restarted local process accepts an existing cookie.

### 2. Sync on visit

- Remove the requirement that a background thread run for the life of the process.
- On `/catalog` or `/media`, if the last successful catalog is older than `SYNC_INTERVAL`, sync before answering.
- Two overlapping requests must not sync the same cache at once. The existing cache lock is enough.
- A failed sync still serves the previous derivatives and sets the existing "Cannot reach the photo library" flag.
- Local `digitalframe serve` may keep a background thread. Function Compute must be correct without one.

Exit check: pytest covers a stale catalog syncing once, and a second overlapping call waiting instead of starting another sync.

### 3. Derivatives in OSS

Function Compute disk is ephemeral and is not shared. Rebuilding every HEIC on every cold slideshow is too slow.

- Publish the same playback bytes the local cache publishes, under a new prefix such as `derivatives/`.
- The object name is derived from the source key, etag, and processing profile. A matching object is reused and not converted again.
- The RAM policy gains `oss:PutObject` and `oss:GetObject` only on `derivatives/*`. `photos/*` stays get-only. There is still no delete of originals.
- Local and ECS runs may keep using the disk cache. The Function Compute configuration selects the OSS derivative store.
- The browser still receives bytes only from the app.

Exit check: pytest uses a fake bucket, shows a second sync skipping a completed derivative, and shows no write under `photos/`.

### 4. Function Compute runbook

Add `deploy/function-compute.md`. Do not create the function in this phase's exit check. The runbook covers:

1. Keep the bucket private and in `cn-hongkong`.
2. Extend the RAM policy as in step 3. Do not use the account root key.
3. Push `digitalframe-2` to a container registry in `cn-hongkong`.
4. Create an HTTP function from that image. Listen on port `9000`, which Function Compute expects. Set `HOST=0.0.0.0`, `PORT=9000`, `COOKIE_SECURE=true`, and `SESSION_KEY`.
5. Memory around 1 GB so a HEIC conversion can finish. Raise the request timeout enough for one conversion. Minimum instances: 0. No provisioned instances. No NAS.
6. Attach a domain and HTTPS. A bare IP is not the target. Do not open the function by handing out OSS links.
7. Confirm a cold visit shows the login page, a passcode plays a photo, and a second visit reuses the stored derivative.

## Left unchanged

Phase 4's Dockerfile, ECS runbook, and commits stay. This phase does not amend them. A disk-backed `digitalframe serve` remains the local and ECS behavior.
