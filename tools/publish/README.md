YouTube uploader for OpenMontage

Purpose

This folder contains the CLI entry point for the YouTube publisher. The actual work is exposed as the `youtube_uploader` publish tool in `tools/publishers/youtube_uploader.py`, and the script in this folder is a thin wrapper for manual runs.

Quick start

1. Create OAuth 2.0 Client ID credentials in Google Cloud Console (Application type: Desktop) and download client_secrets.json.
2. Install the optional Google client stack:
   pip install google-api-python-client google-auth-oauthlib google-auth-httplib2
3. Run the uploader:
   python tools/publish/youtube_uploader.py --export-path exports/<project> --client-secrets /path/to/client_secrets.json --privacy private

Notes

- Tokens are cached in a user-scoped path outside the repo by default: `~/.config/openmontage/.youtube-token.json`, unless `YOUTUBE_TOKEN_PATH` is set explicitly.
- The script expects the export bundle layout produced by the publish director: metadata/metadata.json, video/, thumbnails/.
- This flow is intentionally separated from the offline export tool and uses the least-privilege YouTube upload scope.
