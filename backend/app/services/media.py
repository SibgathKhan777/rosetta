import os
import re
import subprocess


def split_audio(video_path: str, output_dir: str, segment_seconds: int) -> list[tuple[float, str]]:
    """Split into fixed-length WAV segments (16kHz mono, what faster-whisper
    expects). A video shorter than segment_seconds naturally produces a
    single segment — the short-clip case collapses into this same pipeline
    without any special-casing.
    """
    pattern = os.path.join(output_dir, "audio_%03d.wav")
    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        "-f", "segment",
        "-segment_time", str(segment_seconds),
        "-reset_timestamps", "1",
        pattern,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio splitting failed: {result.stderr[-2000:]}")

    files = sorted(f for f in os.listdir(output_dir) if f.startswith("audio_"))
    return [(idx * segment_seconds, os.path.join(output_dir, name)) for idx, name in enumerate(files)]


def extract_interval_frames(video_path: str, output_dir: str, interval_seconds: float) -> list[tuple[float, str]]:
    """Fixed-interval frame candidates — sampling by time rather than by
    scene-change means gradual on-screen changes (slow scrolling, typing)
    are never missed just because the overall scene never "cuts". These are
    candidates only: app.services.text_detector.has_text filters them down
    to frames actually worth OCR'ing.
    """
    pattern = os.path.join(output_dir, "frame_%06d.png")
    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vf", f"fps=1/{interval_seconds},showinfo",
        "-vsync", "vfr",
        pattern,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg interval frame extraction failed: {result.stderr[-2000:]}")

    timestamps = [float(m) for m in re.findall(r"pts_time:([\d.]+)", result.stderr)]
    frames = sorted(f for f in os.listdir(output_dir) if f.startswith("frame_"))
    return list(zip(timestamps, (os.path.join(output_dir, name) for name in frames)))
