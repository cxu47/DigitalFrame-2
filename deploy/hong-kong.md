# Hong Kong host

Run the same `digitalframe serve` process on an Alibaba Cloud ECS instance in `cn-hongkong`, next to the existing private bucket. This does not create the instance. Hong Kong hosting does not require ICP filing.

## 1. Bucket

Use the existing bucket in `cn-hongkong`. Leave it private. Do not turn on static website hosting and do not add a public bucket policy.

## 2. RAM user

Create a RAM user used only by this app. Do not use the account root key. Attach only this policy, with the real bucket name substituted for `BUCKET_NAME`:

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

The policy grants neither `PutObject` nor `DeleteObject`.

## 3. Instance

Create an ECS instance in `cn-hongkong`, about 2 vCPU and 4 GB memory, with a data disk for the cache. Ubuntu 24.04 is enough. Install Docker.

## 4. Security group

Allow inbound TCP 443 from the internet. Allow SSH only from the administrator's address. Do not open port 8000 to the internet.

## 5. Name and TLS

Point a domain name at the instance. A bare IP is not the deployment target. Terminate TLS on the VM with Caddy, which obtains a certificate for that name and reverse-proxies to `127.0.0.1:8000`:

```caddy
photos.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

## 6. Secrets on the VM

Place `users.yaml` and a `secrets` directory on the VM. In `secrets/oss.env`, set:

```dotenv
OSS_ENDPOINT=https://oss-cn-hongkong-internal.aliyuncs.com
```

Listing and downloads then stay on the region-internal network. The first start creates `secrets/session.key`, so that directory must be writable by user id 1000. `users.yaml` can be read-only.

## 7. Start the container

Build `digitalframe-2` from this repository and start it with a restart policy. Publish port 8000 only on the VM's loopback interface, so Caddy is the only public entry:

```bash
docker run -d --name digitalframe --restart unless-stopped \
  -e HOST=0.0.0.0 \
  -e COOKIE_SECURE=true \
  -p 127.0.0.1:8000:8000 \
  -v /opt/digitalframe/secrets:/app/secrets \
  -v /opt/digitalframe/users.yaml:/app/users.yaml:ro \
  -v /var/lib/digitalframe/cache:/app/cache \
  digitalframe-2
```

The cache directory must be writable by user id 1000. Confirm the login page over HTTPS, then confirm a photo plays.
