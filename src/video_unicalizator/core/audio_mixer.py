from __future__ import annotations

import math
from pathlib import Path

try:
    from moviepy import AudioFileClip, CompositeAudioClip, concatenate_audioclips
except ImportError:  # pragma: no cover - зависит от версии moviepy
    from moviepy.editor import AudioFileClip, CompositeAudioClip, concatenate_audioclips


def _subclip(audio_clip, end_time: float):
    if hasattr(audio_clip, "subclipped"):
        return audio_clip.subclipped(0, end_time)
    return audio_clip.subclip(0, end_time)


def _scale_volume(audio_clip, factor: float):
    if hasattr(audio_clip, "with_volume_scaled"):
        return audio_clip.with_volume_scaled(factor)
    if hasattr(audio_clip, "volumex"):
        return audio_clip.volumex(factor)
    return audio_clip


def _build_looped_music(path: Path, duration: float, volume: float):
    music_clip = AudioFileClip(str(path))
    if music_clip.duration <= 0:
        return None

    if music_clip.duration < duration:
        repeat_count = math.ceil(duration / music_clip.duration)
        music_clip = concatenate_audioclips([music_clip] * repeat_count)

    music_clip = _subclip(music_clip, duration)
    return _scale_volume(music_clip, volume)


def mix_audio(video_clip, music_path: Path | None, volume: float):
    """Смешивает оригинальную дорожку с тихой фоновой музыкой."""

    if music_path is None:
        return video_clip.audio

    duration = float(video_clip.duration or 0)
    if duration <= 0:
        return video_clip.audio

    music_clip = _build_looped_music(music_path, duration, volume)
    if music_clip is None:
        return video_clip.audio

    if video_clip.audio is None:
        return music_clip
    return CompositeAudioClip([video_clip.audio, music_clip])

