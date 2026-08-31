Provider-agnostic deploy scaffold — how to enable

This repo contains a deploy scaffold workflow (.github/workflows/deploy-scaffold.yml). It is intentionally non-destructive: provider steps are placeholders that only run when the corresponding repository secrets are present. Configure the secrets below to enable a real deploy.

GCP (Cloud Run)
- Secrets to set in GitHub repository settings → Secrets:
  - GCP_SERVICE_ACCOUNT_KEY — JSON key file contents for a service account with Cloud Run deploy rights (store the whole JSON).
  - GCP_PROJECT — your GCP project id
  - CLOUD_RUN_SERVICE — target Cloud Run service name
  - REGION — region (e.g., us-central1)

AWS (ECR + ECS)
- Secrets:
  - AWS_ACCESS_KEY_ID
  - AWS_SECRET_ACCESS_KEY
  - AWS_REGION
  - ECR_REPOSITORY — e.g., repo/name
  - ECS_CLUSTER
  - ECS_SERVICE

Kubernetes
- Secrets:
  - KUBE_CONFIG — base64-encoded kubeconfig file contents. In the workflow decode it and run kubectl apply.

Enabling a real deploy
1. Add the provider secrets above in the repo Settings → Secrets.
2. Replace the placeholder steps in deploy-scaffold.yml with the provider action/CLI steps you prefer (examples below). The scaffold leaves informative placeholders to avoid accidental deployments.

Example (Cloud Run quick commands):
- echo "$GCP_SERVICE_ACCOUNT_KEY" > /tmp/key.json
- gcloud auth activate-service-account --key-file=/tmp/key.json
- gcloud config set project $GCP_PROJECT
- gcloud run deploy $CLOUD_RUN_SERVICE --image $IMAGE_REF --region $REGION --platform managed --quiet

Security notes
- Do not add raw credentials to the repo. Use repo secrets and restrict access to the repository and Actions as appropriate.
- Review least-privilege for service accounts used by CI. Rotate keys regularly.

If you want, I can add a concrete deploy job for a specific provider (AWS/GCP/Kubernetes) that performs the full push+deploy and includes example secrets and minimal manifest templates. Say which provider and I will add it as a follow-up commit.