import os
import subprocess


def extract_audio(video_path: str, audio_path: str) -> None:
    """16kHz mono PCM WAV — the format faster-whisper expects."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed: {result.stderr[-2000:]}")


def extract_frames(video_path: str, output_dir: str, interval_seconds: float = 2.0) -> list[tuple[float, str]]:
    """Fixed-interval frame extraction (stage 4). Scene-detection to pick
    frame candidates instead of a fixed interval is added in stage 5.
    """
    pattern = os.path.join(output_dir, "frame_%05d.png")
    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vf", f"fps=1/{interval_seconds}",
        pattern,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed: {result.stderr[-2000:]}")

    frames = sorted(f for f in os.listdir(output_dir) if f.startswith("frame_"))
    return [(idx * interval_seconds, os.path.join(output_dir, name)) for idx, name in enumerate(frames)]
