# YouTube Uploader GitHub Actions Workflow

This workflow runs the OpenMontage YouTube uploader as a GitHub Actions job. Use it to automate uploads from your CI/CD pipeline or run on-demand from the Actions tab.

## Setup

1. **Create OAuth credentials** in Google Cloud Console:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a project (or use existing)
   - Enable YouTube Data API v3
   - Create OAuth 2.0 Client ID (Application type: Desktop)
   - Download the JSON file → this is your `client_secrets.json`

2. **Add GitHub secrets** to your repository:
   - Go to **Settings > Secrets and variables > Actions**
   - Add secret `YOUTUBE_CLIENT_SECRETS`: Paste the full contents of `client_secrets.json`
   - (Optional) Add secret `YOUTUBE_REFRESH_TOKEN`: A cached refresh token (see headless setup below)

3. **Push the workflow** to your repository:
   ```bash
   git push origin mhyder2002-del-youtube-uploads
   ```

## Usage

### Via GitHub UI (Recommended for first run)

1. Go to **Actions** tab in GitHub
2. Select **YouTube Uploader** workflow
3. Click **Run workflow**
4. Fill in:
   - `export_path`: Path to export bundle (default: `exports/test-project`)
   - `privacy`: `private`, `unlisted`, or `public`
   - `generate_test`: Check to auto-generate a test bundle
5. Click **Run workflow**
6. Watch the job run and check logs for upload URL

### Via GitHub CLI

```bash
gh workflow run youtube-uploader.yml \
  -f export_path=exports/test-project \
  -f privacy=private \
  -f generate_test=true

# Watch the run:
gh run watch
```

## How it works

1. **Checkout** code from current branch
2. **Install** Python dependencies + ffmpeg
3. **(Optional)** Generate test export bundle via `create_test_bundle.py`
4. **Verify** bundle structure (video file, metadata.json)
5. **Create** `client_secrets.json` from GitHub secret
6. **(Optional)** Pre-create `.youtube-token.json` if refresh token is available (headless), or set YOUTUBE_TOKEN_PATH to a custom path.
7. **Run** uploader: `python tools/publish/youtube_uploader.py ...`
8. **Clean up** sensitive files
9. **Post job summary** with upload results

## Headless / Token Refresh Setup

For fully automated uploads without browser interaction:

1. Run the uploader locally once to generate `.youtube-token.json` (or a local token file):
   ```bash
   python tools/publish/youtube_uploader.py \
     --export-path exports/test-project \
     --client-secrets /path/to/client_secrets.json
   # Follow browser prompt to authorize
   ```

2. Extract and save the `refresh_token` from `.youtube-token.json` (or your local token file):
   ```bash
   cat .youtube-token.json | jq -r .refresh_token
   ```

3. Add this token as GitHub secret `YOUTUBE_REFRESH_TOKEN`

4. The workflow will now:
   - Skip browser OAuth flow
   - Use the refresh token directly for authentication
   - Work fully headless in CI/CD

## Troubleshooting

**"YOUTUBE_CLIENT_SECRETS secret not configured"**
- Add the secret in Settings > Secrets and variables > Actions

**"No video file found in export_path/video/"**
- Ensure the export bundle exists at the specified path
- Or enable `generate_test` to auto-create a test bundle

**"OAuth browser flow not available"**
- This is expected in headless environments
- Set up `YOUTUBE_REFRESH_TOKEN` secret (see Headless setup above)
- Or run the uploader locally once to generate `.youtube-token.json`, then copy it to the workflow (or set YOUTUBE_TOKEN_PATH)

**"403 Unauthorized"**
- Verify your Google OAuth credentials are valid
- Check that YouTube Data API v3 is enabled in Google Cloud Console

## Pricing

The YouTube Data API has quota limits:
- Free tier: 1,000,000 units per day
- Uploading a video costs ~1,500 units
- So free tier allows ~600 uploads/day

For high volume, request quota increase in Google Cloud Console.

## See Also

- `tools/publish/youtube_uploader.py` — Core uploader CLI
- `tools/publish/create_test_bundle.py` — Test bundle generator
- `Makefile` — `make youtube-upload`, `make youtube-test-bundle`, `make youtube-demo`
