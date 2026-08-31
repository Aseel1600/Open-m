"""YouTube uploader for OpenMontage export bundles.

Usage:
  python tools/publish/youtube_uploader.py --export-path path/to/exports/<project> \
    --client-secrets client_secrets.json

The script performs an OAuth2 installed-app flow (opens browser), caches credentials
in .youtube-token.json (not committed), reads metadata from the export bundle
(metadata/metadata.json), and uploads the video with metadata and optional thumbnail.

Dependencies (added to requirements.txt):
  google-api-python-client, google-auth-oauthlib, google-auth-httplib2

This uploader is intentionally minimal and uses resumable uploads.
"""
import argparse
import sys

from tools.publishers.youtube_uploader import YouTubeUploader


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload an OpenMontage export bundle to YouTube.")
    parser.add_argument("--export-path", required=True, help="Path to the export bundle (exports/<project>)")
    parser.add_argument("--client-secrets", required=True, help="Path to the Google OAuth client_secrets.json")
    parser.add_argument("--privacy", choices=["public", "private", "unlisted"], default="private")
    parser.add_argument("--thumbnail", default=None, help="Optional thumbnail path (overrides the exported thumbnail)")
    parser.add_argument("--token-path", default=None, help="Optional refresh-token cache path. Defaults to ~/.config/openmontage/.youtube-token.json")
    args = parser.parse_args()

    tool = YouTubeUploader()
    result = tool.execute({
        "video_path": None,
        "client_secrets_path": args.client_secrets,
        "export_path": args.export_path,
        "privacy": args.privacy,
        "thumbnail_path": args.thumbnail,
        "token_path": args.token_path,
    })

    if not result.success:
        print(result.error, file=sys.stderr)
        return 1

    print(f"Upload complete: {result.data['youtube_url']}")
    if args.thumbnail:
        print(f"Thumbnail set: {result.data['thumbnail_set']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
