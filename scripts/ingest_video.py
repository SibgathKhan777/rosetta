#!/usr/bin/env python3
"""Download a video locally and hand it to a deployed instance's
POST /jobs/ingest endpoint — for platforms (e.g. YouTube) that block
requests from the server's IP range but not from a regular residential/
home connection.

Requires: pip install yt-dlp requests

Usage:
    python3 ingest_video.py <video_url> <api_base_url> <jwt_token>

Get a JWT token by logging into the deployed frontend, opening browser
devtools, and reading localStorage.getItem('token') — or via curl:
    curl -X POST <api_base_url>/auth/login -H "Content-Type: application/json" \\
      -d '{"email": "you@example.com", "password": "..."}'
"""
import os
import sys
import tempfile

import requests
import yt_dlp


def main() -> None:
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)

    url, api_base, token = sys.argv[1], sys.argv[2], sys.argv[3]

    tmp_dir = tempfile.mkdtemp(prefix="ingest-")
    ydl_opts = {
        "outtmpl": os.path.join(tmp_dir, "source.%(ext)s"),
        "format": "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    candidates = [f for f in os.listdir(tmp_dir) if f.startswith("source.")]
    if not candidates:
        print("ERROR: yt-dlp reported success but produced no output file")
        sys.exit(1)
    local_path = os.path.join(tmp_dir, candidates[0])

    data = {
        "url": url,
        "title": info.get("title") or "",
        "caption": info.get("description") or "",
        "uploader": info.get("uploader") or "",
        "view_count": info.get("view_count") or 0,
        "like_count": info.get("like_count") or 0,
        "comment_count": info.get("comment_count") or 0,
        "duration_seconds": info.get("duration") or 0,
    }
    print(f"Uploading {os.path.basename(local_path)} ({os.path.getsize(local_path) / 1e6:.1f} MB)...")
    with open(local_path, "rb") as f:
        resp = requests.post(
            f"{api_base.rstrip('/')}/jobs/ingest",
            data=data,
            files={"file": (os.path.basename(local_path), f)},
            headers={"Authorization": f"Bearer {token}"},
        )
    print(resp.status_code, resp.text)


if __name__ == "__main__":
    main()
