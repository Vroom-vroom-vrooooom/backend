# Backend deployment

Workflow: [Backend CI and deploy](https://github.com/Vroom-vroom-vrooooom/backend/actions/workflows/deploy.yml).

## Triggers and release checks

- Pull requests targeting `main`: locked dependencies and the full pytest suite on Python 3.12.
- Pushes to `main`, including merges: tests followed by production deployment.
- `workflow_dispatch` on `main`: explicit deployment or retry from the Actions page.

Deployments for a branch are serialized. An active deployment is not cancelled by another push. Actions are pinned to commit SHAs.

The deploy job builds the tested commit and pushes it to `asia-northeast3-docker.pkg.dev/vroom-514610/chagok-images/chagok-api`. Cloud Run receives the image digest, a commit label and a revision named `chagok-api-gh-<run-id>-<attempt>`. The mutable `candidate` tag addresses the new revision while existing production traffic remains unchanged.

`deploy/verify_release.py` checks `/health`, exact equality of the deployed `/openapi.json` with the checked-out application schema, Swagger UI and unauthenticated rejection by `/v1/trips`. Only after these checks pass does the workflow send 100% of production traffic to that revision. It checks the production URL again and writes links and the revision to the run summary. A candidate failure leaves production on its previous revision. A failure after promotion requires the rollback command below; rollback is not automatic.

These routine checks are read-only. They do not create users, access Firestore records or call Claude. `deploy/smoke.py` is the separate administrator-run functional check for real Firestore, pairing, device events and Claude; it creates and cleans up synthetic data and requires server-side credentials. Set `SMOKE_RESULTS_PATH` to store its evidence outside the checkout without triggering another deployment. Unit tests mock AI and persistence.

## One-time GCP bootstrap

Run as a project administrator with an authenticated Google Cloud CLI:

```powershell
./deploy/bootstrap-github.ps1 -Gcloud /path/to/gcloud.cmd
```

The script is safe to rerun. Existing runtime secrets, Firestore configuration and application settings are prerequisites; it does not rotate them.

| Resource | Configuration |
| --- | --- |
| Project / region | `vroom-514610` / `asia-northeast3` |
| Cloud Run service | `chagok-api` |
| Deployment identity | `chagok-github-deploy@vroom-514610.iam.gserviceaccount.com` |
| Workload identity pool / provider | `github-actions` / `backend-main` |
| Artifact Registry | `chagok-images` |

The provider accepts the immutable repository ID `1456469220` and owner ID `355321586`, `refs/heads/main`, this repository's `.github/workflows/deploy.yml` on `main`, and only `push` or `workflow_dispatch` events. Pull requests cannot use this identity. Allow several minutes for new IAM bindings to propagate before the first run.

The deployment identity has `roles/run.developer` on this Cloud Run service, `roles/iam.serviceAccountUser` on `chagok-runtime`, `roles/artifactregistry.writer` on `chagok-images`, and `roles/serviceusage.serviceUsageConsumer` on the project. The matching federated principal has `roles/iam.workloadIdentityUser` on the deployment identity. There are no downloadable keys or GitHub application-secret copies. Runtime secret values remain in Secret Manager and are read by `chagok-runtime`.

The workflow preserves existing environment variables, version-pinned secret references, scaling, resource limits and public ingress. It changes the image, revision, labels and traffic. No app or FE files are deployed by this repository.

## Rollback

Use an administrator identity. Find the previous known-good revision in the earlier successful Actions summary or list revisions, then route traffic to that explicit revision:

```powershell
gcloud run revisions list --service=chagok-api --project=vroom-514610 --region=asia-northeast3
gcloud run services update-traffic chagok-api --project=vroom-514610 --region=asia-northeast3 --to-revisions=PREVIOUS_REVISION=100
```

Also revert the faulty code on `main` so the next deployment contains the fix. Deployment authentication uses GitHub OIDC and a short-lived access token; retry a timed-out authentication run rather than introducing a permanent key.
