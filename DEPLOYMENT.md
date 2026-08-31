Deployment artifacts and usage

This repository now contains a minimal Dockerfile and a GitHub Actions workflow that builds and publishes a container image to GitHub Container Registry (ghcr.io).

What was added
- Dockerfile — builds a Python image using requirements.txt (if present).
- .github/workflows/docker-build-and-publish.yml — builds and pushes the image to ghcr.io/${{ github.repository_owner }}/openmontage:latest on push to main or via manual dispatch.

How to use
1. Review the Dockerfile and replace the default CMD with your service entrypoint.
2. Commit and push changes to the branch. The workflow can be triggered manually from the Actions UI or by pushing to `main` / `mhyder2002-del-youtube-uploads`.
3. The workflow uses `secrets.GITHUB_TOKEN` to authenticate to ghcr; ensure the repository has `packages: write` permission for the workflow's token.

Notes and safety
- This does not perform any production deployment. It only builds and publishes a container image to the registry.
- To actually deploy the image (ECS, Cloud Run, Kubernetes, etc.), add a deployment job that uses appropriate cloud credentials stored in repository secrets and a controlled approval step.

Next steps (optional)
- Add a second workflow to deploy the built image to your chosen cloud provider using repository secrets.
- Add Terraform manifests or Helm charts for infrastructure provisioning.
- Configure required `secrets` (DOCKER_REGISTRY, CLOUD_PROVIDER_CREDS) and protect the main branch before enabling automatic deploys.
