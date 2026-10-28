"""Download one video with yt-dlp; no sidecar metadata or paid API."""
from pathlib import Path
import subprocess
import sys

def download_video(url, directory, video_id):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([sys.executable, '-m', 'yt_dlp', '--no-playlist',
        '--no-write-info-json', '--no-write-thumbnail', '--no-write-subs',
        '--merge-output-format', 'mp4', '--remux-video', 'mp4',
        '-o', str(directory / (video_id + '.%(ext)s')), url],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240)
    target = directory / (video_id + '.mp4')
    if result.returncode or not target.is_file():
        raise RuntimeError('yt-dlp download failed; inspect authenticated browser/session before retrying')
    return target
