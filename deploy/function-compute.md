# Function Compute

Run the same slideshow as a custom container in Alibaba Cloud Function Compute, region `cn-hongkong`. A visit wakes it. Idle time does not keep a virtual machine. This page does not create the function.

The app reads originals from the private bucket. JPEG, PNG, and WebP are unchanged. HEIC and HEIF are converted in memory for that response and are not saved. The signed cookie holds folder, months, and seconds per photo.

## 1. Bucket

Keep the existing bucket private and in `cn-hongkong`. Do not turn on static website hosting and do not add a public bucket policy.

## 2. RAM user

Use a RAM user for this app only. Do not use the account root key. Attach only list and get on the photos prefix:

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

Replace `BUCKET_NAME`. The policy grants neither `PutObject` nor `DeleteObject`.

## 3. Image

Push the `digitalframe-2` image to a container registry in `cn-hongkong`.

## 4. Environment variables

Create an HTTP function from that image. Function Compute calls port `9000`. Do not put `secrets/oss.env` or `users.yaml` in the image or on a disk. A file mount needs a NAS volume, which bills every month, so this setup uses one passcode variable instead of a user file.

In the Function Compute console, open the function, then **Configuration**, then **Environment variables**. Add each row below. Use the console's secret option for the key, the secret, the session key, and the passcode when it is offered. Do not add spaces around the passcode. The value is compared exactly.

| Name | Value |
| --- | --- |
| `HOST` | `0.0.0.0` |
| `PORT` | `9000` |
| `COOKIE_SECURE` | `true` |
| `BACKGROUND_SYNC` | `false` |
| `OSS_ACCESS_KEY_ID` | the RAM user's id |
| `OSS_ACCESS_KEY_SECRET` | the RAM user's secret |
| `OSS_BUCKET_NAME` | the existing bucket |
| `OSS_REGION` | `cn-hongkong` |
| `OSS_ENDPOINT` | `https://oss-cn-hongkong-internal.aliyuncs.com` |
| `OSS_PREFIX` | `photos` |
| `SESSION_KEY` | 64 hex characters from `python -c "import secrets; print(secrets.token_hex(32))"` |
| `PASSCODE` | the one passcode people type on the login page |

When `OSS_ACCESS_KEY_ID` is present, the process does not read `secrets/oss.env`. When `PASSCODE` is present, it does not read `users.yaml`. Local runs leave both unset and keep using those files. The names in `users.yaml` are not used here.

## 5. Capacity

Use about 2 GB of memory so one full-resolution HEIC can be converted. Raise the request timeout enough for that conversion. Minimum instances: 0. Do not use provisioned instances, a NAS disk, or a derivative prefix.

## 6. Name and TLS

Attach a domain and HTTPS. A bare IP is not the target. Do not give viewers an OSS URL.

## 7. Check

Open the site after it has been idle. The login page appears after the cold start. A passcode plays a photo read from OSS. A HEIC plays, and the bucket does not gain a new object.
