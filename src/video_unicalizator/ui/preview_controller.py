from __future__ import annotations

from pathlib import Path

from video_unicalizator.config import PREVIEW_PLAYBACK_FPS
from video_unicalizator.state import VideoTimelineProfile
from video_unicalizator.ui.preview_support import PreviewPlaybackController, PreviewVideoWorker


class ManagedPreviewPlaybackController(PreviewPlaybackController):
    """Неблокирующий preview-controller с приоритетом плавности playback."""

    def play(self) -> None:
        if self._preview.video_path is None:
            return

        self._reset_runtime_sessions()
        video_path = self._preview.video_path
        proxy_size = self._preview.get_playback_proxy_size()
        self._video_worker = PreviewVideoWorker()
        self._video_worker.start(
            video_path=video_path,
            start_sec=self._preview.get_playhead(),
            target_size=proxy_size,
            max_fps=PREVIEW_PLAYBACK_FPS,
        )
        self._preview.start_proxy_playback(self._video_worker)

        timeline = self._get_timeline()
        music_tracks = self._get_music_tracks()
        enabled, volume = self._get_music_preview_settings()
        cached_audio = self._audio_cache.peek(
            source_video=video_path,
            timeline=timeline,
            music_tracks=music_tracks,
            music_preview_enabled=enabled,
            music_preview_volume=volume,
        )

        if cached_audio is not None:
            self._start_audio_session(cached_audio)
            return

        if self._requires_async_audio_mix(timeline, music_tracks, enabled):
            self._audio_request_id += 1
            request_id = self._audio_request_id
            self._preview.set_runtime_status("Preview: preparing audio mix...")
            self._audio_cache.request_async(
                source_video=video_path,
                timeline=timeline.copy(),
                music_tracks=list(music_tracks),
                music_preview_enabled=enabled,
                music_preview_volume=volume,
                callback=lambda audio_source: self._queue_audio_finish(request_id, audio_source),
            )
            return

        audio_source = self._audio_cache.get_or_create(
            source_video=video_path,
            timeline=timeline,
            music_tracks=music_tracks,
            music_preview_enabled=enabled,
            music_preview_volume=volume,
        )
        self._start_audio_session(audio_source)

    def _run_audio_prewarm(self) -> None:
        self._prewarm_after_id = None
        video_path = self._preview.video_path
        if video_path is None:
            return

        timeline = self._get_timeline()
        music_tracks = self._get_music_tracks()
        enabled, volume = self._get_music_preview_settings()
        if not self._requires_async_audio_mix(timeline, music_tracks, enabled):
            return

        self._audio_cache.request_async(
            source_video=video_path,
            timeline=timeline.copy(),
            music_tracks=list(music_tracks),
            music_preview_enabled=enabled,
            music_preview_volume=volume,
        )

    def _queue_audio_finish(self, request_id: int, audio_source: Path | None) -> None:
        try:
            self._preview.after(0, lambda: self._finish_audio_request(request_id, audio_source))
        except Exception:
            return
