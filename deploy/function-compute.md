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

## 4. Function

Create an HTTP function from that image. Function Compute calls port `9000`. Set:

```text
HOST=0.0.0.0
PORT=9000
COOKIE_SECURE=true
BACKGROUND_SYNC=false
SESSION_KEY=<64 hex characters>
```

Create the key with `python -c "import secrets; print(secrets.token_hex(32))"`. Put the OSS settings in the function environment as well: `OSS_ACCESS_KEY_ID`, `OSS_ACCESS_KEY_SECRET`, `OSS_BUCKET_NAME`, `OSS_REGION=cn-hongkong`, and `OSS_ENDPOINT=https://oss-cn-hongkong-internal.aliyuncs.com`. Mount `users.yaml` where the process expects `USERS_FILE`, or set the passcode file contents through the platform's file facility. Do not bake secrets into the image.

## 5. Capacity

Use about 2 GB of memory so one full-resolution HEIC can be converted. Raise the request timeout enough for that conversion. Minimum instances: 0. Do not use provisioned instances, a NAS disk, or a derivative prefix.

## 6. Name and TLS

Attach a domain and HTTPS. A bare IP is not the target. Do not give viewers an OSS URL.

## 7. Check

Open the site after it has been idle. The login page appears after the cold start. A passcode plays a photo read from OSS. A HEIC plays, and the bucket does not gain a new object.
