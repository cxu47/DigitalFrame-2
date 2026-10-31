# Phase 5 — Function Compute

Date: 2026-10-30  
Status: implemented in the app. The Function Compute service itself is not created; follow [../deploy/function-compute.md](../deploy/function-compute.md).  
Requires: [04-hong-kong-host.md](04-hong-kong-host.md) stays in place. The ECS runbook is not removed.  
Next: none. Implementation waits for an explicit go-ahead.

## Evaluation

Alibaba Cloud Function Compute in `cn-hongkong` fits the new hosting goal: a visit wakes the app, and idle time does not pay for a virtual machine. The product name is Function Compute. A custom container is the right shape, because phase 4 already builds `digitalframe-2`.

The current process cannot be moved unchanged. Three things assume a machine that stays on:

| Current behavior | Why it breaks at zero instances | Replacement |
| --- | --- | --- |
| Sessions live in process memory | The next visit can start a new instance that has never seen the cookie | A signed cookie that carries the view by itself |
| A background thread syncs forever | Nothing runs while the function is frozen | List the bucket when a visit finds the catalog stale |
| Photos are scaled and stored on a local disk | That disk disappears with the instance, and the scaled copy is no longer wanted | Read the original object from OSS. Convert HEIC in memory for that request only |

What stays: the photo rules, passcode file, canvas playback, focus blackout, translations, and the phase 4 ECS path. Local `digitalframe serve` and the ECS container keep working. Function Compute is a second way to run the same app.

Idle cost stays small only if these are refused:

- A minimum instance count above zero. That is a virtual machine again.
- Provisioned instances.
- A NAS disk. It bills every month whether or not anyone visits.
- A timer that wakes the function on a schedule. Sync happens on a visit instead.

Standing cost is then OSS storage for the original photos, plus the container image in a registry in `cn-hongkong`. There is no second copy of the pictures. Compute is billed for the seconds a visit keeps an instance awake, including a short platform grace period after the last request. The first visit after a quiet stretch waits through a cold start, often several seconds, before the login page appears.

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

### 2. Read the originals

Drop the 1600×900 bound and the disk cache. The app lists `photos/` and loads each object from OSS when the page asks for it. Nothing is written back to the bucket.

- JPEG, PNG, and WebP are streamed through as stored. They are not scaled, recompressed, or saved.
- HEIC and HEIF are decoded in memory and returned as a JPEG for that response only. The JPEG is not stored in OSS, on disk, or for the next request.
- The browser still receives bytes only from the app. It never receives an OSS URL.
- RAM stays list and get on `photos/*`. No `PutObject`.
- A full-resolution HEIC needs room in RAM. Size the function around 2 GB. One conversion must finish inside the request timeout.
- A failed list still returns the last catalog held in that instance, and sets "Cannot reach the photo library". A cold instance with no catalog yet shows the waiting screen.

Exit check: pytest uses a fake bucket. A JPEG response matches the object bytes. A HEIC response is a JPEG and does not create an object. No test writes under `photos/`.

### 3. List on visit

- Remove the requirement that a background thread run for the life of the process.
- On `/catalog` or `/media`, if the last successful list is older than `SYNC_INTERVAL`, list again before answering.
- Two overlapping requests must not list the same bucket at once.
- Local `digitalframe serve` may keep a background thread. Function Compute must be correct without one.

Exit check: pytest covers a stale catalog listing once, and a second overlapping call waiting instead of starting another list.

### 4. Function Compute runbook

Add `deploy/function-compute.md`. Do not create the function in this phase's exit check. The runbook covers:

1. Keep the bucket private and in `cn-hongkong`.
2. Keep the RAM policy as list and get on `photos/*` only. Do not use the account root key.
3. Push `digitalframe-2` to a container registry in `cn-hongkong`.
4. Create an HTTP function from that image. Listen on port `9000`. The process reads configuration from the function environment, not from `secrets/oss.env` or `users.yaml`. Set `HOST=0.0.0.0`, `PORT=9000`, `COOKIE_SECURE=true`, `BACKGROUND_SYNC=false`, `SESSION_KEY`, `PASSCODE`, and the `OSS_*` variables.
5. Memory around 2 GB so one full-resolution HEIC can be converted in memory. Raise the request timeout enough for that conversion. Minimum instances: 0. No provisioned instances. No NAS. No derivative prefix.
6. Attach a domain and HTTPS. A bare IP is not the target. Do not open the function by handing out OSS links.
7. Confirm a cold visit shows the login page, a passcode plays a photo loaded from OSS, and a HEIC plays without a file being written back.

## Left unchanged

Phase 4's Dockerfile, ECS runbook, and commits stay. This phase does not amend them. When this phase is built, local and ECS `digitalframe serve` use the same read path: originals from OSS, no scaling, HEIC converted in memory per request. The settings that are kept are only the signed cookie: folder, months, and seconds per photo.
