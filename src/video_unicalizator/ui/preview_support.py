from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image, ImageOps

from video_unicalizator.config import (
    PREVIEW_PLAYBACK_FPS,
    PREVIEW_PROXY_MAX_HEIGHT,
    PREVIEW_PROXY_MAX_WIDTH,
    TIMELINE_FADE_SECONDS,
)
from video_unicalizator.state import MusicClip, VideoTimelineProfile, resolve_music_track_bindings
from video_unicalizator.utils.ffmpeg_tools import (
    ensure_ffmpeg_environment,
    no_window_creationflags,
    probe_media,
    resolve_binary,
)
from video_unicalizator.utils.image_tools import fit_cover_frame
from video_unicalizator.utils.temp_paths import project_temp_root


@dataclass(slots=True)
class PreviewMusicAssignment:
    clip_id: str
    start_sec: float
    end_sec: float
    volume: float
    track: Path | None
    track_offset_sec: float = 0.0
    cycle_index: int = 0


def assign_preview_music_clips(clips: list[MusicClip], tracks: list[Path]) -> list[PreviewMusicAssignment]:
    assignments: list[PreviewMusicAssignment] = []
    enabled = [clip for clip in sorted(clips, key=lambda item: (item.start_sec, item.end_sec, item.clip_id)) if clip.enabled]
    if not enabled:
        return assignments

    bindings = resolve_music_track_bindings(enabled, tracks)
    for clip in enabled:
        fallback_track = clip.bound_track if clip.track_locked else None
        track, cycle_index = bindings.get(clip.clip_id, (fallback_track, 0))
        assignments.append(
            PreviewMusicAssignment(
                clip_id=clip.clip_id,
                start_sec=clip.start_sec,
                end_sec=clip.end_sec,
                volume=clip.volume,
                track=track,
                track_offset_sec=max(0.0, float(clip.track_offset_sec)),
                cycle_index=cycle_index,
            )
        )
    return assignments


class WaveformCache:
    def __init__(self) -> None:
        self._cache: dict[str, list[float]] = {}
        self._pending: set[str] = set()
        self._lock = threading.Lock()

    def key_for(self, track: Path | None, *, points: int = 96) -> str | None:
        if track is None or not track.exists():
            return None
        stat = track.stat()
        return f"{track.resolve()}:{stat.st_mtime_ns}:{stat.st_size}:{points}"

    def peek(self, track: Path | None, *, points: int = 96) -> list[float] | None:
        key = self.key_for(track, points=points)
        if key is None:
            return [0.0] * points
        with self._lock:
            return self._cache.get(key)

    def get(self, track: Path | None, *, points: int = 96) -> list[float]:
        key = self.key_for(track, points=points)
        if key is None:
            return [0.0] * points
        cached = self.peek(track, points=points)
        if cached is not None:
            return cached

        ffmpeg_path, _ = ensure_ffmpeg_environment()
        if ffmpeg_path is None:
            peaks = [0.0] * points
        else:
            command = [
                ffmpeg_path,
                "-v",
                "error",
                "-i",
                str(track),
                "-ac",
                "1",
                "-ar",
                "2000",
                "-f",
                "s16le",
                "-",
            ]
            completed = subprocess.run(
                command,
                capture_output=True,
                check=False,
                creationflags=no_window_creationflags(),
            )
            if completed.returncode != 0 or not completed.stdout:
                peaks = [0.0] * points
            else:
                samples = np.frombuffer(completed.stdout, dtype=np.int16).astype(np.float32)
                if samples.size == 0:
                    peaks = [0.0] * points
                else:
                    chunk = max(1, int(np.ceil(samples.size / points)))
                    peaks = []
                    for offset in range(0, samples.size, chunk):
                        segment = samples[offset : offset + chunk]
                        peaks.append(float(np.max(np.abs(segment)) / 32768.0))
                    if len(peaks) < points:
                        peaks.extend([0.0] * (points - len(peaks)))
                    peaks = peaks[:points]

        with self._lock:
            self._cache[key] = peaks
        return peaks

    def request_async(self, track: Path | None, *, points: int = 96, callback: Callable[[], None] | None = None) -> None:
        key = self.key_for(track, points=points)
        if key is None or self.peek(track, points=points) is not None:
            if callback is not None:
                callback()
            return

        with self._lock:
            if key in self._pending:
                return
            self._pending.add(key)

        def worker() -> None:
            try:
                self.get(track, points=points)
            finally:
                with self._lock:
                    self._pending.discard(key)
                if callback is not None:
                    callback()

        threading.Thread(target=worker, daemon=True).start()


class ThumbnailStripCache:
    def __init__(self) -> None:
        self._cache: dict[str, list[Image.Image]] = {}
        self._pending: set[str] = set()
        self._tile_cache: dict[str, Image.Image] = {}
        self._pending_tiles: set[str] = set()
        self._lock = threading.Lock()

    def key_for(self, video_path: Path | None, *, count: int = 10, size: tuple[int, int] = (72, 42)) -> str | None:
        if video_path is None or not video_path.exists():
            return None
        stat = video_path.stat()
        return f"{video_path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}:{count}:{size[0]}x{size[1]}"

    def peek(self, video_path: Path | None, *, count: int = 10, size: tuple[int, int] = (72, 42)) -> list[Image.Image] | None:
        key = self.key_for(video_path, count=count, size=size)
        if key is None:
            return []
        with self._lock:
            return self._cache.get(key)

    def get(self, video_path: Path | None, *, count: int = 10, size: tuple[int, int] = (72, 42)) -> list[Image.Image]:
        key = self.key_for(video_path, count=count, size=size)
        if key is None:
            return []
        cached = self.peek(video_path, count=count, size=size)
        if cached is not None:
            return cached

        capture = cv2.VideoCapture(str(video_path))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        images: list[Image.Image] = []
        try:
            positions = np.linspace(0, max(0, frame_count - 1), num=max(1, count), dtype=int)
            for frame_index in positions:
                capture.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
                ok, frame = capture.read()
                if not ok:
                    continue
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = Image.fromarray(rgb)
                thumb = ImageOps.fit(image, size, Image.Resampling.LANCZOS, centering=(0.5, 0.5))
                images.append(thumb)
        finally:
            capture.release()

        with self._lock:
            self._cache[key] = images
        return images

    def request_async(
        self,
        video_path: Path | None,
        *,
        count: int = 10,
        size: tuple[int, int] = (72, 42),
        callback: Callable[[], None] | None = None,
    ) -> None:
        key = self.key_for(video_path, count=count, size=size)
        if key is None or self.peek(video_path, count=count, size=size) is not None:
            if callback is not None:
                callback()
            return

        with self._lock:
            if key in self._pending:
                return
            self._pending.add(key)

        def worker() -> None:
            try:
                self.get(video_path, count=count, size=size)
            finally:
                with self._lock:
                    self._pending.discard(key)
                if callback is not None:
                    callback()

        threading.Thread(target=worker, daemon=True).start()

    def tile_key_for(
        self,
        video_path: Path | None,
        *,
        bucket_index: int,
        seconds_per_tile: float,
        size: tuple[int, int] = (96, 60),
    ) -> str | None:
        if video_path is None or not video_path.exists():
            return None
        stat = video_path.stat()
        return (
            f"{video_path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}:"
            f"tile:{bucket_index}:{seconds_per_tile:.4f}:{size[0]}x{size[1]}"
        )

    def peek_tile(
        self,
        video_path: Path | None,
        *,
        bucket_index: int,
        seconds_per_tile: float,
        size: tuple[int, int] = (96, 60),
    ) -> Image.Image | None:
        key = self.tile_key_for(video_path, bucket_index=bucket_index, seconds_per_tile=seconds_per_tile, size=size)
        if key is None:
            return None
        with self._lock:
            return self._tile_cache.get(key)

    def get_filmstrip_tiles(
        self,
        video_path: Path | None,
        *,
        bucket_indices: list[int],
        seconds_per_tile: float,
        duration: float,
        size: tuple[int, int] = (96, 60),
    ) -> dict[int, Image.Image]:
        if video_path is None or not video_path.exists() or not bucket_indices:
            return {}

        normalized_buckets = sorted({max(0, int(bucket)) for bucket in bucket_indices})
        if not normalized_buckets:
            return {}

        result: dict[int, Image.Image] = {}
        missing: list[int] = []
        for bucket_index in normalized_buckets:
            cached = self.peek_tile(
                video_path,
                bucket_index=bucket_index,
                seconds_per_tile=seconds_per_tile,
                size=size,
            )
            if cached is not None:
                result[bucket_index] = cached
            else:
                missing.append(bucket_index)

        if not missing:
            return result

        capture = cv2.VideoCapture(str(video_path))
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        media_duration = max(duration, 0.0)
        if media_duration <= 0.0:
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
            media_duration = frame_count / max(fps, 1.0)
        max_seek = max(0.0, media_duration - (1.0 / max(fps, 1.0)))

        try:
            for bucket_index in missing:
                midpoint_sec = min(max_seek, max(0.0, (bucket_index + 0.5) * seconds_per_tile))
                capture.set(cv2.CAP_PROP_POS_MSEC, midpoint_sec * 1000.0)
                ok, frame = capture.read()
                if not ok:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(midpoint_sec * fps))))
                    ok, frame = capture.read()
                if not ok:
                    continue
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = Image.fromarray(rgb)
                tile = ImageOps.fit(image, size, Image.Resampling.LANCZOS, centering=(0.5, 0.5))
                key = self.tile_key_for(
                    video_path,
                    bucket_index=bucket_index,
                    seconds_per_tile=seconds_per_tile,
                    size=size,
                )
                if key is None:
                    continue
                with self._lock:
                    self._tile_cache[key] = tile
                result[bucket_index] = tile
        finally:
            capture.release()

        return result

    def request_filmstrip_async(
        self,
        video_path: Path | None,
        *,
        bucket_indices: list[int],
        seconds_per_tile: float,
        duration: float,
        size: tuple[int, int] = (96, 60),
        callback: Callable[[], None] | None = None,
    ) -> None:
        if video_path is None or not video_path.exists() or not bucket_indices:
            if callback is not None:
                callback()
            return

        pending_keys: list[str] = []
        missing_buckets: list[int] = []
        for bucket_index in sorted({max(0, int(bucket)) for bucket in bucket_indices}):
            key = self.tile_key_for(
                video_path,
                bucket_index=bucket_index,
                seconds_per_tile=seconds_per_tile,
                size=size,
            )
            if key is None:
                continue
            if self.peek_tile(
                video_path,
                bucket_index=bucket_index,
                seconds_per_tile=seconds_per_tile,
                size=size,
            ) is not None:
                continue
            pending_keys.append(key)
            missing_buckets.append(bucket_index)

        if not missing_buckets:
            if callback is not None:
                callback()
            return

        with self._lock:
            unresolved = [key for key in pending_keys if key not in self._pending_tiles]
            if not unresolved:
                return
            for key in unresolved:
                self._pending_tiles.add(key)

        def worker() -> None:
            try:
                self.get_filmstrip_tiles(
                    video_path,
                    bucket_indices=missing_buckets,
                    seconds_per_tile=seconds_per_tile,
                    duration=duration,
                    size=size,
                )
            finally:
                with self._lock:
                    for key in pending_keys:
                        self._pending_tiles.discard(key)
                if callback is not None:
                    callback()

        threading.Thread(target=worker, daemon=True).start()


class PreviewAudioCache:
    def __init__(self) -> None:
        self._cache_dir = project_temp_root("preview_audio")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._pending: set[str] = set()
        self._callbacks: dict[str, list[Callable[[Path | None], None]]] = {}

    def peek(
        self,
        *,
        source_video: Path | None,
        timeline: VideoTimelineProfile,
        music_tracks: list[Path],
        music_preview_enabled: bool,
        music_preview_volume: float,
    ) -> Path | None:
        output_path, media_info, assignments, _ffmpeg_path, _digest = self._describe_request(
            source_video=source_video,
            timeline=timeline,
            music_tracks=music_tracks,
            music_preview_enabled=music_preview_enabled,
            music_preview_volume=music_preview_volume,
        )
        if output_path is None or media_info is None:
            return None
        if not assignments:
            return source_video if media_info.has_audio else None
        return output_path if output_path.exists() else None

    def state_for(
        self,
        *,
        source_video: Path | None,
        timeline: VideoTimelineProfile,
        music_tracks: list[Path],
        music_preview_enabled: bool,
        music_preview_volume: float,
    ) -> str:
        output_path, media_info, assignments, ffmpeg_path, digest = self._describe_request(
            source_video=source_video,
            timeline=timeline,
            music_tracks=music_tracks,
            music_preview_enabled=music_preview_enabled,
            music_preview_volume=music_preview_volume,
        )
        if output_path is None or media_info is None:
            return "unavailable"
        if not assignments:
            return "ready" if media_info.has_audio else "unavailable"
        if ffmpeg_path is None:
            return "unavailable"
        if output_path.exists():
            return "ready"
        with self._lock:
            if digest in self._pending:
                return "building"
        return "stale"

    def request_async(
        self,
        *,
        source_video: Path | None,
        timeline: VideoTimelineProfile,
        music_tracks: list[Path],
        music_preview_enabled: bool,
        music_preview_volume: float,
        callback: Callable[[Path | None], None] | None = None,
    ) -> None:
        output_path, media_info, assignments, ffmpeg_path, digest = self._describe_request(
            source_video=source_video,
            timeline=timeline,
            music_tracks=music_tracks,
            music_preview_enabled=music_preview_enabled,
            music_preview_volume=music_preview_volume,
        )
        if output_path is None or media_info is None:
            if callback is not None:
                callback(None)
            return
        if not assignments:
            if callback is not None:
                callback(source_video if media_info.has_audio else None)
            return
        if ffmpeg_path is None:
            if callback is not None:
                callback(None)
            return
        if output_path.exists():
            if callback is not None:
                callback(output_path)
            return

        with self._lock:
            if callback is not None:
                self._callbacks.setdefault(digest, []).append(callback)
            if digest in self._pending:
                return
            self._pending.add(digest)

        def worker() -> None:
            result: Path | None = None
            try:
                result = self.get_or_create(
                    source_video=source_video,
                    timeline=timeline.copy(),
                    music_tracks=list(music_tracks),
                    music_preview_enabled=music_preview_enabled,
                    music_preview_volume=music_preview_volume,
                )
            finally:
                with self._lock:
                    callbacks = self._callbacks.pop(digest, [])
                    self._pending.discard(digest)
            for queued_callback in callbacks:
                try:
                    queued_callback(result)
                except Exception:
                    continue

        threading.Thread(target=worker, daemon=True).start()

    def get_or_create(
        self,
        *,
        source_video: Path | None,
        timeline: VideoTimelineProfile,
        music_tracks: list[Path],
        music_preview_enabled: bool,
        music_preview_volume: float,
    ) -> Path | None:
        if source_video is None or not source_video.exists():
            return None

        output_path, media_info, assignments, ffmpeg_path, _digest = self._describe_request(
            source_video=source_video,
            timeline=timeline,
            music_tracks=music_tracks,
            music_preview_enabled=music_preview_enabled,
            music_preview_volume=music_preview_volume,
        )
        if output_path is None or media_info is None:
            return None
        if not assignments:
            return source_video if media_info.has_audio else None
        if ffmpeg_path is None:
            return None
        if output_path.exists():
            return output_path

        command = [ffmpeg_path, "-y", "-v", "error", "-i", str(source_video)]
        music_inputs: list[PreviewMusicAssignment] = []
        for assignment in assignments:
            if assignment.track is None or not assignment.track.exists():
                continue
            command.extend(["-i", str(assignment.track)])
            music_inputs.append(assignment)

        filters: list[str] = []
        audio_label: str | None = None
        if media_info.has_audio:
            filters.append("[0:a]aresample=async=1:first_pts=0[voice]")
            audio_label = "voice"

        music_labels: list[str] = []
        for index, assignment in enumerate(music_inputs, start=1):
            duration = max(0.05, assignment.end_sec - assignment.start_sec)
            delay_ms = max(0, int(round(assignment.start_sec * 1000)))
            fade_duration = min(TIMELINE_FADE_SECONDS, max(0.0, duration / 2.0))
            music_label = f"music{index}"
            steps = [
                f"atrim=start={max(0.0, assignment.track_offset_sec):.3f}:duration={duration:.3f}",
                "asetpts=PTS-STARTPTS",
                f"volume={max(0.0, min(2.0, music_preview_volume * assignment.volume)):.3f}",
            ]
            if fade_duration > 0:
                steps.append(f"afade=t=in:st=0:d={fade_duration:.3f}")
                steps.append(f"afade=t=out:st={max(0.0, duration - fade_duration):.3f}:d={fade_duration:.3f}")
            steps.append(f"adelay={delay_ms}|{delay_ms}")
            steps.append("aresample=async=1:first_pts=0")
            filters.append(f"[{index}:a]{','.join(steps)}[{music_label}]")
            music_labels.append(music_label)

        if music_labels:
            if len(music_labels) == 1:
                filters.append(f"[{music_labels[0]}]anull[musicbus]")
            else:
                merged = "".join(f"[{label}]" for label in music_labels)
                filters.append(f"{merged}amix=inputs={len(music_labels)}:normalize=0:duration=longest[musicbus]")
            if audio_label is None:
                filters.append("[musicbus]anull[aout]")
            else:
                filters.append(f"[{audio_label}][musicbus]amix=inputs=2:normalize=0:duration=longest[aout]")
            audio_label = "aout"

        if audio_label is None:
            return None

        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                f"[{audio_label}]",
                "-t",
                f"{media_info.duration:.3f}",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                str(output_path),
            ]
        )
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            creationflags=no_window_creationflags(),
        )
        if completed.returncode != 0:
            return source_video if media_info.has_audio else None
        return output_path

    def _describe_request(
        self,
        *,
        source_video: Path | None,
        timeline: VideoTimelineProfile,
        music_tracks: list[Path],
        music_preview_enabled: bool,
        music_preview_volume: float,
    ) -> tuple[Path | None, object | None, list[PreviewMusicAssignment], str | None, str]:
        if source_video is None or not source_video.exists():
            return None, None, [], None, ""

        media_info = probe_media(source_video)
        assignments = assign_preview_music_clips(timeline.music_clips, music_tracks) if music_preview_enabled else []
        if not assignments:
            return source_video, media_info, [], None, ""

        ffmpeg_path, _ = ensure_ffmpeg_environment()
        payload = {
            "source": str(source_video.resolve()),
            "source_mtime": source_video.stat().st_mtime_ns,
            "duration": round(media_info.duration, 3),
            "music_enabled": music_preview_enabled,
            "music_volume": round(music_preview_volume, 3),
            "assignments": [
                {
                    "clip_id": item.clip_id,
                    "start": round(item.start_sec, 3),
                    "end": round(item.end_sec, 3),
                    "volume": round(item.volume, 3),
                    "track_offset": round(item.track_offset_sec, 3),
                    "track": str(item.track.resolve()) if item.track is not None else None,
                    "track_mtime": item.track.stat().st_mtime_ns if item.track is not None and item.track.exists() else 0,
                }
                for item in assignments
            ],
        }
        digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        return self._cache_dir / f"{digest}.m4a", media_info, assignments, ffmpeg_path, digest


@dataclass(slots=True)
class PreviewFramePacket:
    frame_rgb: np.ndarray | None
    playhead_sec: float
    finished: bool = False


class PreviewFrameBuffer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._version = 0
        self._packet = PreviewFramePacket(frame_rgb=None, playhead_sec=0.0, finished=False)

    def push(self, packet: PreviewFramePacket) -> None:
        with self._lock:
            self._version += 1
            self._packet = packet

    def read(self, last_version: int = 0) -> tuple[int, PreviewFramePacket | None]:
        with self._lock:
            if self._version == last_version:
                return self._version, None
            return self._version, self._packet


class PreviewVideoWorker:
    def __init__(self) -> None:
        self.buffer = PreviewFrameBuffer()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(
        self,
        *,
        video_path: Path,
        start_sec: float,
        target_size: tuple[int, int],
        max_fps: int = PREVIEW_PLAYBACK_FPS,
    ) -> None:
        self.stop()
        self.buffer = PreviewFrameBuffer()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(video_path, start_sec, target_size, max_fps),
            daemon=True,
        )
        self._thread.start()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=0.12)
        self._thread = None

    def _run(self, video_path: Path, start_sec: float, target_size: tuple[int, int], max_fps: int) -> None:
        capture = cv2.VideoCapture(str(video_path))
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        output_fps = max(12.0, min(float(max_fps), float(fps)))
        frame_step = max(1, int(round(max(fps, 1.0) / max(output_fps, 1.0))))
        frame_number = max(0, int(round(start_sec * fps)))
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        frame_interval = 1.0 / max(output_fps, 1.0)
        next_tick = time.perf_counter()
        last_playhead = max(0.0, start_sec)

        try:
            while not self._stop_event.is_set():
                ok, frame = capture.read()
                if not ok:
                    break

                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                proxy_frame = fit_cover_frame(
                    frame_rgb,
                    target_width=min(PREVIEW_PROXY_MAX_WIDTH, max(1, target_size[0])),
                    target_height=min(PREVIEW_PROXY_MAX_HEIGHT, max(1, target_size[1])),
                    interpolation=cv2.INTER_LINEAR,
                )
                playhead_sec = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                if playhead_sec <= 0.0:
                    playhead_sec = max(0.0, capture.get(cv2.CAP_PROP_POS_FRAMES) / max(fps, 1.0))
                last_playhead = playhead_sec
                self.buffer.push(PreviewFramePacket(frame_rgb=proxy_frame, playhead_sec=playhead_sec, finished=False))

                if frame_step > 1:
                    for _ in range(frame_step - 1):
                        if self._stop_event.is_set() or not capture.grab():
                            break

                next_tick += frame_interval
                sleep_for = next_tick - time.perf_counter()
                if sleep_for > 0:
                    if self._stop_event.wait(min(sleep_for, 0.05)):
                        break
                else:
                    next_tick = time.perf_counter()
        finally:
            capture.release()
            self.buffer.push(PreviewFramePacket(frame_rgb=None, playhead_sec=last_playhead, finished=True))


class PreviewAudioSession:
    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None

    def is_available(self) -> bool:
        return resolve_binary("ffplay.exe") is not None or resolve_binary("ffplay") is not None

    def play(self, audio_source: Path | None, *, start_sec: float) -> bool:
        ffplay_path = resolve_binary("ffplay.exe") or resolve_binary("ffplay")
        if ffplay_path is None or audio_source is None or not Path(audio_source).exists():
            return False
        self.stop()
        command = [
            ffplay_path,
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0.0, start_sec):.3f}",
            str(audio_source),
        ]
        self._process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=no_window_creationflags(),
        )
        return True

    def stop(self) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=1.2)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
        self._process = None


class PreviewPlaybackController:
    def __init__(
        self,
        *,
        preview_widget,
        get_timeline: Callable[[], VideoTimelineProfile],
        get_music_tracks: Callable[[], list[Path]],
        get_music_preview_settings: Callable[[], tuple[bool, float]],
    ) -> None:
        self._preview = preview_widget
        self._get_timeline = get_timeline
        self._get_music_tracks = get_music_tracks
        self._get_music_preview_settings = get_music_preview_settings
        self._audio_cache = PreviewAudioCache()
        self._audio_session = PreviewAudioSession()
        self._video_worker: PreviewVideoWorker | None = None
        self._audio_request_id = 0
        self._prewarm_after_id: str | None = None

    def _reset_runtime_sessions(self) -> None:
        self._audio_request_id += 1
        self._audio_session.stop()
        if self._video_worker is not None:
            self._video_worker.stop()
            self._video_worker = None

    def toggle_playback(self) -> None:
        if self._preview.is_playing():
            self.pause()
        else:
            self.play()

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

        if self._requires_async_audio_mix(timeline, music_tracks, enabled):
            self._audio_request_id += 1
            request_id = self._audio_request_id
            self._preview.set_runtime_status("Preview: подготавливаю audio mix...")

            def worker() -> None:
                audio_source = self._audio_cache.get_or_create(
                    source_video=video_path,
                    timeline=timeline.copy(),
                    music_tracks=list(music_tracks),
                    music_preview_enabled=enabled,
                    music_preview_volume=volume,
                )
                try:
                    self._preview.after(0, lambda: self._finish_audio_request(request_id, audio_source))
                except Exception:
                    return

            threading.Thread(target=worker, daemon=True).start()
            return

        audio_source = self._audio_cache.get_or_create(
            source_video=video_path,
            timeline=timeline,
            music_tracks=music_tracks,
            music_preview_enabled=enabled,
            music_preview_volume=volume,
        )
        self._start_audio_session(audio_source)

    def pause(self) -> None:
        self._reset_runtime_sessions()
        self._preview._pause_local_playback()
        self._preview.set_runtime_status(None)

    def stop(self) -> None:
        self._reset_runtime_sessions()
        self._preview._stop_local_playback()
        self._preview.set_runtime_status(None)

    def restart(self) -> None:
        self.stop()
        self._preview._restart_local_playback()
        self.play()

    def handle_external_seek(self) -> None:
        if self._preview.is_playing():
            self.stop()

    def schedule_audio_prewarm(self, delay_ms: int = 220) -> None:
        if self._preview.video_path is None:
            return
        if self._prewarm_after_id is not None:
            try:
                self._preview.after_cancel(self._prewarm_after_id)
            except Exception:
                pass
        self._prewarm_after_id = self._preview.after(delay_ms, self._run_audio_prewarm)

    def shutdown(self) -> None:
        if self._prewarm_after_id is not None:
            try:
                self._preview.after_cancel(self._prewarm_after_id)
            except Exception:
                pass
            self._prewarm_after_id = None
        self.stop()

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

        def worker() -> None:
            self._audio_cache.get_or_create(
                source_video=video_path,
                timeline=timeline.copy(),
                music_tracks=list(music_tracks),
                music_preview_enabled=enabled,
                music_preview_volume=volume,
            )

        threading.Thread(target=worker, daemon=True).start()

    def _requires_async_audio_mix(
        self,
        timeline: VideoTimelineProfile,
        music_tracks: list[Path],
        music_preview_enabled: bool,
    ) -> bool:
        if not music_preview_enabled or not music_tracks:
            return False
        return any(clip.enabled for clip in timeline.music_clips)

    def _finish_audio_request(self, request_id: int, audio_source: Path | None) -> None:
        if request_id != self._audio_request_id or not self._preview.is_playing():
            return
        self._start_audio_session(audio_source)

    def _start_audio_session(self, audio_source: Path | None) -> None:
        if audio_source is None:
            self._preview.set_runtime_status("Preview: видео играет без аудио-дорожки.")
            return
        started = self._audio_session.play(audio_source, start_sec=self._preview.get_playhead())
        if started:
            self._preview.set_runtime_status("Preview: плавное воспроизведение таймлайна с аудио.")
        else:
            self._preview.set_runtime_status("Preview: ffplay недоступен, аудио в preview отключено.")
