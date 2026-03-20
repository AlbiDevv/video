from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from video_unicalizator.config import SPEED_MAX, SPEED_MIN
from video_unicalizator.core.video_processor import FILTER_PRESETS
from video_unicalizator.services.music_loader import MusicChoice
from video_unicalizator.state import ColorGradeProfile, GenerationSettings

MIN_RECIPE_DISTANCE = 2.15
REJECTED_RECIPE_NEIGHBOURHOOD = 1.45


@dataclass(slots=True, frozen=True)
class VariationRecipe:
    speed_factor: float
    trim_start: float
    trim_end: float
    duration_key: int
    output_duration: float
    filter_preset: str
    brightness_variant: int
    contrast_variant: int
    saturation_variant: int
    accent_strength_variant: int
    crop_family: str
    crop_anchor: str
    sharpen_enabled: bool
    music_track: Path | None
    music_cycle_index: int
    recipe_key: str
    visual_key: tuple

    def short_label(self) -> str:
        track_name = self.music_track.name if self.music_track is not None else "без_музыки"
        return f"preset={self.filter_preset}, duration={self.output_duration:.1f}, track={track_name}"


@dataclass(slots=True, frozen=True)
class RecipeDistanceScore:
    score: float
    nearest_recipe_key: str | None = None
    nearest_factors: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class PlannedRecipeCandidate:
    recipe: VariationRecipe
    distance: RecipeDistanceScore


@dataclass(slots=True)
class SourceUniquenessLedger:
    accepted_recipes: list[VariationRecipe] = field(default_factory=list)
    rejected_recipes: list[VariationRecipe] = field(default_factory=list)
    accepted_duration_keys: set[int] = field(default_factory=set)
    accepted_recipe_keys: set[str] = field(default_factory=set)
    accepted_visual_keys: set[tuple] = field(default_factory=set)
    rejected_recipe_keys: set[str] = field(default_factory=set)
    rejected_visual_keys: set[tuple] = field(default_factory=set)

    def record_accepted(self, recipe: VariationRecipe) -> None:
        self.accepted_recipes.append(recipe)
        self.accepted_duration_keys.add(recipe.duration_key)
        self.accepted_recipe_keys.add(recipe.recipe_key)
        self.accepted_visual_keys.add(recipe.visual_key)

    def record_rejected(self, recipe: VariationRecipe) -> None:
        self.rejected_recipes.append(recipe)
        self.rejected_recipe_keys.add(recipe.recipe_key)
        self.rejected_visual_keys.add(recipe.visual_key)


class VariationRecipePlanner:
    def __init__(
        self,
        *,
        source_video: Path,
        source_duration: float,
        settings: GenerationSettings,
        color_grade: ColorGradeProfile,
    ) -> None:
        self.source_video = source_video
        self.source_duration = source_duration
        self.settings = settings
        self.color_grade = color_grade
        self.precision = max(settings.duration_uniqueness_precision, 0.01)
        self.min_trimmed_duration = max(1.6, min(source_duration * 0.82, source_duration - 0.35))
        self.max_trim = min(max(0.0, source_duration * 0.18), 1.9)
        self._seed = self._build_seed()
        self._rng = random.Random(self._seed)
        self._sample_round = 0
        self._speed_options = self._build_speed_options()
        self._trim_options = self._build_trim_options()

    def next_recipe(
        self,
        ledger: SourceUniquenessLedger,
        music_choice: MusicChoice,
    ) -> PlannedRecipeCandidate | None:
        if not ledger.accepted_recipes and not ledger.rejected_recipes:
            bootstrap = self._bootstrap_recipe(music_choice)
            return PlannedRecipeCandidate(bootstrap, RecipeDistanceScore(score=99.0))

        candidates = self._sample_candidates(music_choice)
        best: PlannedRecipeCandidate | None = None
        best_score = float("-inf")

        for recipe in candidates:
            if recipe.duration_key in ledger.accepted_duration_keys:
                continue
            if recipe.visual_key in ledger.accepted_visual_keys:
                continue
            if recipe.recipe_key in ledger.accepted_recipe_keys:
                continue
            if recipe.visual_key in ledger.rejected_visual_keys or recipe.recipe_key in ledger.rejected_recipe_keys:
                continue

            rejected_distance = self.score_against(recipe, ledger.rejected_recipes)
            if ledger.rejected_recipes and rejected_distance.score < REJECTED_RECIPE_NEIGHBOURHOOD:
                continue

            accepted_distance = self.score_against(recipe, ledger.accepted_recipes)
            if ledger.accepted_recipes and accepted_distance.score < MIN_RECIPE_DISTANCE:
                continue

            if ledger.accepted_recipes:
                score = accepted_distance.score + min(0.8, rejected_distance.score * 0.15)
            else:
                score = self._intrinsic_score(recipe)

            if score > best_score:
                best = PlannedRecipeCandidate(recipe=recipe, distance=accepted_distance)
                best_score = score

        return best

    def score_against(
        self,
        recipe: VariationRecipe,
        references: Iterable[VariationRecipe],
    ) -> RecipeDistanceScore:
        nearest_recipe_key: str | None = None
        nearest_score = float("inf")
        nearest_factors: tuple[str, ...] = ()

        for reference in references:
            score = self.recipe_distance(recipe, reference)
            if score < nearest_score:
                nearest_score = score
                nearest_recipe_key = reference.recipe_key
                nearest_factors = self.closest_factors(recipe, reference)

        if nearest_recipe_key is None:
            return RecipeDistanceScore(score=99.0)
        return RecipeDistanceScore(
            score=nearest_score,
            nearest_recipe_key=nearest_recipe_key,
            nearest_factors=nearest_factors,
        )

    def recipe_distance(self, left: VariationRecipe, right: VariationRecipe) -> float:
        duration_gap = min(2.5, abs(left.duration_key - right.duration_key) * 0.35)
        speed_gap = min(1.4, abs(left.speed_factor - right.speed_factor) / max(SPEED_MAX - SPEED_MIN, 0.01) * 1.4)
        trim_start_gap = min(1.0, abs(left.trim_start - right.trim_start) / max(self.max_trim, 0.01))
        trim_end_gap = min(1.0, abs(left.trim_end - right.trim_end) / max(self.max_trim, 0.01))
        contrast_gap = abs(left.contrast_variant - right.contrast_variant) * 0.22
        saturation_gap = abs(left.saturation_variant - right.saturation_variant) * 0.22
        brightness_gap = abs(left.brightness_variant - right.brightness_variant) * 0.18
        accent_gap = abs(left.accent_strength_variant - right.accent_strength_variant) * 0.16

        score = duration_gap + speed_gap + trim_start_gap + trim_end_gap + contrast_gap + saturation_gap + brightness_gap + accent_gap
        if left.filter_preset != right.filter_preset:
            score += 0.95
        if left.sharpen_enabled != right.sharpen_enabled:
            score += 0.28
        if left.music_track != right.music_track:
            score += 0.18
        if left.music_cycle_index != right.music_cycle_index:
            score += 0.08
        return score

    def closest_factors(self, left: VariationRecipe, right: VariationRecipe) -> tuple[str, ...]:
        factors: list[str] = []
        if abs(left.duration_key - right.duration_key) <= 1:
            factors.append("duration")
        if abs(left.speed_factor - right.speed_factor) <= 0.025:
            factors.append("speed")
        if abs(left.trim_start - right.trim_start) <= 0.20:
            factors.append("trim_start")
        if abs(left.trim_end - right.trim_end) <= 0.20:
            factors.append("trim_end")
        if left.filter_preset == right.filter_preset:
            factors.append("filter")
        if left.brightness_variant == right.brightness_variant:
            factors.append("brightness")
        if left.contrast_variant == right.contrast_variant:
            factors.append("contrast")
        if left.saturation_variant == right.saturation_variant:
            factors.append("saturation")
        if left.accent_strength_variant == right.accent_strength_variant:
            factors.append("accent")
        if left.sharpen_enabled == right.sharpen_enabled:
            factors.append("sharpen")
        if left.music_track == right.music_track and left.music_track is not None:
            factors.append("music")
        return tuple(factors)

    def _intrinsic_score(self, recipe: VariationRecipe) -> float:
        preset_bonus = list(FILTER_PRESETS).index(recipe.filter_preset) * 0.08
        tone_bonus = (
            abs(recipe.brightness_variant)
            + abs(recipe.contrast_variant)
            + abs(recipe.saturation_variant)
            + abs(recipe.accent_strength_variant)
        ) * 0.16
        speed_bonus = abs(recipe.speed_factor - 1.0) * 2.8
        duration_bonus = abs(recipe.output_duration - self.source_duration) * 0.10
        sharpen_bonus = 0.18 if recipe.sharpen_enabled else 0.0
        return preset_bonus + tone_bonus + speed_bonus + duration_bonus + sharpen_bonus

    def _sample_candidates(self, music_choice: MusicChoice) -> list[VariationRecipe]:
        self._sample_round += 1
        sample_size = max(120, self.settings.candidate_search_attempts * 4)
        max_iterations = sample_size * 20
        candidates: list[VariationRecipe] = []
        seen_visual_keys: set[tuple] = set()

        for _ in range(max_iterations):
            recipe = self._random_recipe(music_choice)
            if recipe.visual_key in seen_visual_keys:
                continue
            seen_visual_keys.add(recipe.visual_key)
            candidates.append(recipe)
            if len(candidates) >= sample_size:
                break
        return candidates

    def _random_recipe(self, music_choice: MusicChoice) -> VariationRecipe:
        speed_factor = self._rng.choice(self._speed_options)
        trim_start = self._rng.choice(self._trim_options)
        trim_end = self._rng.choice(self._trim_options)
        trimmed_duration = self.source_duration - trim_start - trim_end

        if trimmed_duration < self.min_trimmed_duration:
            shortage = self.min_trimmed_duration - trimmed_duration
            trim_end = max(0.0, trim_end - shortage)
            trimmed_duration = self.source_duration - trim_start - trim_end
            if trimmed_duration < self.min_trimmed_duration:
                trim_start = max(0.0, trim_start - (self.min_trimmed_duration - trimmed_duration))

        trimmed_duration = max(0.12, self.source_duration - trim_start - trim_end)
        output_duration = max(0.10, trimmed_duration / max(speed_factor, 0.01))
        duration_key = int(round(output_duration / self.precision))
        filter_preset = self._rng.choice(tuple(FILTER_PRESETS))
        brightness_variant = self._rng.choice((-1, 0, 1))
        contrast_variant = self._rng.choice((-1, 0, 1))
        saturation_variant = self._rng.choice((-1, 0, 1))
        accent_strength_variant = self._rng.choice((-1, 0, 1))
        sharpen_enabled = bool(self.settings.enhance_sharpness and self._rng.choice((0, 1)))
        return self._build_recipe(
            speed_factor=speed_factor,
            trim_start=trim_start,
            trim_end=trim_end,
            duration_key=duration_key,
            output_duration=output_duration,
            filter_preset=filter_preset,
            brightness_variant=brightness_variant,
            contrast_variant=contrast_variant,
            saturation_variant=saturation_variant,
            accent_strength_variant=accent_strength_variant,
            crop_family="neutral",
            crop_anchor="center",
            sharpen_enabled=sharpen_enabled,
            music_choice=music_choice,
        )

    def _bootstrap_recipe(self, music_choice: MusicChoice) -> VariationRecipe:
        presets = tuple(FILTER_PRESETS)
        preset_index = self._seed % len(presets)
        speed_options = sorted(self._speed_options, key=lambda value: abs(value - 1.0))
        speed_factor = speed_options[min(1, len(speed_options) - 1)]
        trim_value = min(self.max_trim, 0.22 + (self._seed % 5) * 0.08)
        trim_start = round(trim_value, 2)
        trim_end = round(max(0.0, trim_value * 0.55), 2)
        trimmed_duration = max(0.12, self.source_duration - trim_start - trim_end)
        output_duration = max(0.10, trimmed_duration / max(speed_factor, 0.01))
        duration_key = int(round(output_duration / self.precision))
        return self._build_recipe(
            speed_factor=speed_factor,
            trim_start=trim_start,
            trim_end=trim_end,
            duration_key=duration_key,
            output_duration=output_duration,
            filter_preset=presets[preset_index],
            brightness_variant=0,
            contrast_variant=1,
            saturation_variant=0,
            accent_strength_variant=0,
            crop_family="neutral",
            crop_anchor="center",
            sharpen_enabled=False,
            music_choice=music_choice,
        )

    def _build_recipe(
        self,
        *,
        speed_factor: float,
        trim_start: float,
        trim_end: float,
        duration_key: int,
        output_duration: float,
        filter_preset: str,
        brightness_variant: int,
        contrast_variant: int,
        saturation_variant: int,
        accent_strength_variant: int,
        crop_family: str,
        crop_anchor: str,
        sharpen_enabled: bool,
        music_choice: MusicChoice,
    ) -> VariationRecipe:
        music_name = music_choice.track.name.lower() if music_choice.track is not None else "nomusic"
        visual_key = (
            duration_key,
            filter_preset,
            round(speed_factor, 3),
            round(trim_start, 2),
            round(trim_end, 2),
            brightness_variant,
            contrast_variant,
            saturation_variant,
            accent_strength_variant,
            int(sharpen_enabled),
        )
        recipe_key = "|".join(
            (
                str(duration_key),
                filter_preset,
                f"{speed_factor:.3f}",
                f"{trim_start:.2f}",
                f"{trim_end:.2f}",
                str(brightness_variant),
                str(contrast_variant),
                str(saturation_variant),
                str(accent_strength_variant),
                "sh1" if sharpen_enabled else "sh0",
                music_name,
                f"cycle{music_choice.cycle_index}",
            )
        )
        return VariationRecipe(
            speed_factor=speed_factor,
            trim_start=trim_start,
            trim_end=trim_end,
            duration_key=duration_key,
            output_duration=output_duration,
            filter_preset=filter_preset,
            brightness_variant=brightness_variant,
            contrast_variant=contrast_variant,
            saturation_variant=saturation_variant,
            accent_strength_variant=accent_strength_variant,
            crop_family=crop_family,
            crop_anchor=crop_anchor,
            sharpen_enabled=sharpen_enabled,
            music_track=music_choice.track,
            music_cycle_index=music_choice.cycle_index,
            recipe_key=recipe_key,
            visual_key=visual_key,
        )

    def _build_seed(self) -> int:
        raw = f"{self.source_video}|{self.source_duration:.3f}|{self.settings.variation_count}".encode("utf-8")
        digest = hashlib.blake2b(raw, digest_size=8).digest()
        return int.from_bytes(digest, "big", signed=False)

    def _build_speed_options(self) -> list[float]:
        option_count = 8
        if option_count <= 1:
            return [round((SPEED_MIN + SPEED_MAX) / 2.0, 3)]
        step = (SPEED_MAX - SPEED_MIN) / (option_count - 1)
        return [round(SPEED_MIN + step * index, 3) for index in range(option_count)]

    def _build_trim_options(self) -> list[float]:
        max_trim = max(0.0, self.max_trim)
        if max_trim <= 0:
            return [0.0]
        steps = max(6, min(10, int(max_trim / 0.18) + 2))
        values = [round(max_trim * index / max(1, steps - 1), 2) for index in range(steps)]
        return sorted(set(values))
