# Pipeline deployment on Almiraj

`Build pipeline image` builds Linux ARM64 on a GitHub-hosted runner. It verifies cache imports and generated contracts, starts the image, and exercises revision reporting, rejected unauthenticated requests and authenticated resource search with a synthetic cache fixture. The fixture lives only in the test container, not in the published image. Only main-branch images are published to `bosla26/bosla-pipeline:<full commit SHA>` and `:latest`.

`Deploy pipeline to Almiraj` runs only after a successful main-branch image build or an explicit dispatch of main. It uses a repository-scoped Almiraj runner, calls `bosla-deploy pipeline <SHA>`, and verifies the exact revision plus authenticated search over **https://pipeline.almiraj.xyz**. The existing shared secret is stored as the Pipeline repository's `PIPELINE_SHARED_SECRET` Actions secret. It is separate from the one-hour runner registration token.

The obsolete Hugging Face sync remains disabled. Keep the deployment workflow disabled until the administrator setup below is finished; building and publishing an image does not change the running server.

## One-time administrator setup

The patch in `server.patch` was prepared against the previously verified migration bundle. Apply its small changes to the current canonical `/etc/nixos` source, preserving subsequent administrator changes. `git apply --check` must succeed before applying automatically; otherwise reconcile the shown changes manually.

1. Preserve the current working pipeline image and source/configuration backup. Before changing the Nix image name, tag the running image as `bosla26/bosla-pipeline:latest` locally. That provides a working baseline for activation and for the helper's first rollback. Do not push the old local recovery image to a registry.
2. Add the new repository-scoped runner `bosla-pipeline` for `https://github.com/Bosla-Ai/Pipeline`, using the same `bosla-runner` account, package, sandbox settings and labels as the working API/frontend runners. Store the supplied fresh registration token in SOPS as `bosla-pipeline-runner-token`. Preserve existing runner credentials and both existing token entries.
3. Apply the helper changes: `pipeline` selects repository `bosla26/bosla-pipeline`, container `bosla-pipeline`, system unit `bosla-pipeline.service`, and health URL `http://127.0.0.1:7860/health`. Retain the existing SHA validation, fixed Docker socket/credentials, deployment lock and rollback logic.
4. Set the pipeline Nix container image to `bosla26/bosla-pipeline:latest` with `pull = "never"`. **Remove the current local build-from-`/opt/bosla-pipeline` hook** so restarting cannot overwrite the image selected by the deployment helper. This hook is not present in the older baseline patch; inspect the current service definition. Keep the existing environment-file projection, production authentication flags, network, ports and Caddy configuration.
5. Build and activate `/etc/nixos#almiraj`. Ensure deployment queues are empty before starting the new runner. Confirm the three runners are online and idle, and that the old pipeline image remains healthy immediately after activation.
6. Confirm the runner environment can execute the existing restricted sudo helper and has Python 3. The patch adds Python to its packages. Root's existing Docker Hub pull credentials must also allow the pipeline repository.

After the administrator confirms setup, enable the new deployment workflow and dispatch it on main. The deployment helper selects the published SHA image, restarts the service and restores the previous image if HTTP readiness fails. The subsequent HTTPS/authenticated-search step reports failures to GitHub Actions; it does not itself roll back a service that passed the helper's readiness check.

Success means all of these agree: the completed main image build SHA, the deployed image selected by the helper, the `/health` revision over HTTPS, an unauthenticated search returning 401, and an authenticated search returning 200 with candidates.

## Scope of this image

The image runs the current stateless HTTP tools with browser scraping disabled, matching the repaired Almiraj deployment. It includes Redis and the existing startup script. It does not restore retired Socket.IO or `/generate-roadmap` routes, and does not include Google Chrome or Microsoft SQL Server ODBC drivers. Browser-based scrapers and direct SQL integrations need a separately validated image/configuration if enabled later.
