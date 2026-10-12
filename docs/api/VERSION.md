# Application release identity

`GET /version` is a read-only technical endpoint available on the API domain and
local backend. Response: `{"git_sha":"<40-character-lowercase-hex-SHA>"}` for a
release image, or `{"git_sha":null}` for a development checkout without baked
metadata. No credentials, user data, image pull tokens, filesystem paths or DB
state are returned. It requires no DB connection or upstream call.

The SHA comes from image-owned `release.json`, validated during build and import;
environment variables cannot change it. Invalid baked metadata prevents startup.
OCI revision labels and worker `worker_started.git_sha` identify the same release.
`/healthz` and `/dbz` retain their existing contracts. The main domain continues
to expose only its configured surfaces; no Caddy change is necessary.

See [release publication, retention and rollback](../../ops/releases/README.md).
