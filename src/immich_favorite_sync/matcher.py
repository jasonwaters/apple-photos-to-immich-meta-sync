"""Asset matching logic for Photos favorites to Immich assets."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import PurePath

from .immich_client import ImmichAsset, ImmichClient
from .models import FavoritePhoto

logger = logging.getLogger(__name__)


class MatchConfidence(Enum):
    """Confidence level for asset matches."""

    HIGH = "high"  # Strong filename + metadata match
    MEDIUM = "medium"  # Single filename match with partial metadata
    AMBIGUOUS = "ambiguous"  # Multiple potential matches
    NONE = "none"  # No matches found


@dataclass
class MatchResult:
    """Result of matching a source favorite to Immich assets."""

    source_photo: FavoritePhoto
    confidence: MatchConfidence
    immich_asset: ImmichAsset | None = None
    candidates: list[ImmichAsset] = None
    reason: str = ""

    def __post_init__(self):
        """Initialize candidates list."""
        if self.candidates is None:
            self.candidates = []


class AssetMatcher:
    """Matcher for finding Immich assets corresponding to Photos favorites."""

    STRONG_MATCH_SCORE = 80
    PARTIAL_MATCH_SCORE = 50
    EXACT_TIMESTAMP_SCORE = 55
    TIGHT_DATE_WINDOW_MINUTES = 2

    def __init__(self, immich_client: ImmichClient, date_tolerance_days: int = 2):
        """Initialize matcher.

        Args:
            immich_client: Immich API client
            date_tolerance_days: Days of tolerance when matching by date
        """
        self.immich_client = immich_client
        self.date_tolerance_days = date_tolerance_days

    def match(self, photo: FavoritePhoto) -> MatchResult:
        """Find the best match for a Photos favorite in Immich.

        Args:
            photo: Photos favorite metadata

        Returns:
            MatchResult with confidence level and matched asset
        """
        logger.debug(f"Matching source favorite: {photo}")

        return self._match_by_metadata(photo)

    def _match_by_metadata(self, photo: FavoritePhoto) -> MatchResult:
        """Match by filename and metadata.

        Args:
            photo: Photos favorite metadata

        Returns:
            MatchResult
        """
        try:
            candidates, query_score = self._search_filename_candidates(photo)

            if not candidates:
                return MatchResult(
                    source_photo=photo,
                    confidence=MatchConfidence.NONE,
                    reason="No filename match",
                )

            candidates = self._filter_exact_filename(candidates, self._filename_variants(photo))

            if not candidates:
                return MatchResult(
                    source_photo=photo,
                    confidence=MatchConfidence.NONE,
                    reason="No exact filename match",
                )

            if len(candidates) == 1 and query_score >= self.STRONG_MATCH_SCORE:
                return MatchResult(
                    source_photo=photo,
                    confidence=MatchConfidence.HIGH,
                    immich_asset=candidates[0],
                    candidates=candidates,
                    reason=f"Specific Immich metadata query score {query_score}",
                )

            if len(candidates) == 1 and query_score >= self.EXACT_TIMESTAMP_SCORE:
                return MatchResult(
                    source_photo=photo,
                    confidence=MatchConfidence.MEDIUM,
                    immich_asset=candidates[0],
                    candidates=candidates,
                    reason=f"Specific Immich metadata query score {query_score}",
                )

            best_candidate, best_score, tied_candidates = self._rank_candidates(photo, candidates)

            if best_candidate and best_score >= self.EXACT_TIMESTAMP_SCORE:
                if len(tied_candidates) > 1:
                    logger.info(
                        "Multiple timestamp matches for %s; favoriting one deterministic duplicate",
                        photo.filename,
                    )

                return MatchResult(
                    source_photo=photo,
                    confidence=MatchConfidence.MEDIUM,
                    immich_asset=best_candidate,
                    candidates=tied_candidates,
                    reason=f"Filename + timestamp score {best_score}",
                )

            enrichment_targets = tied_candidates or candidates
            force_enrichment = 0 < best_score < self.PARTIAL_MATCH_SCORE
            enriched_candidates = self._enrich_candidates(enrichment_targets, force=force_enrichment)
            best_candidate, best_score, tied_candidates = self._rank_candidates(photo, enriched_candidates)

            if best_candidate and best_score >= self.STRONG_MATCH_SCORE:
                if len(tied_candidates) > 1:
                    logger.info(
                        "Multiple strong metadata matches for %s; favoriting one deterministic duplicate",
                        photo.filename,
                    )

                logger.debug(f"Strong metadata match found for {photo.filename} with score {best_score}")
                return MatchResult(
                    source_photo=photo,
                    confidence=MatchConfidence.HIGH,
                    immich_asset=best_candidate,
                    candidates=tied_candidates,
                    reason=f"Filename + metadata score {best_score}",
                )

            if len(enriched_candidates) == 1 and best_candidate and best_score >= self.PARTIAL_MATCH_SCORE:
                logger.debug(f"Partial metadata match found for {photo.filename} with score {best_score}")
                return MatchResult(
                    source_photo=photo,
                    confidence=MatchConfidence.MEDIUM,
                    immich_asset=best_candidate,
                    candidates=enriched_candidates,
                    reason=f"Single filename + partial metadata score {best_score}",
                )

            logger.warning(
                "Could not confidently choose one match for %s; best metadata score was %s across %s candidates",
                photo.filename,
                best_score,
                len(enriched_candidates),
            )
            return MatchResult(
                source_photo=photo,
                confidence=MatchConfidence.AMBIGUOUS,
                candidates=enriched_candidates,
                reason=f"Best metadata score {best_score} across {len(enriched_candidates)} candidates",
            )

        except Exception as e:
            logger.error(f"Error matching by metadata: {e}")
            return MatchResult(
                source_photo=photo,
                confidence=MatchConfidence.NONE,
                reason=f"Metadata search error: {e}",
            )

    def _search_filename_candidates(self, photo: FavoritePhoto) -> tuple[list[ImmichAsset], int]:
        """Search Immich from most-specific metadata to broad filename."""
        best_weak_candidates: list[ImmichAsset] = []
        best_weak_score = 0

        filename_variants = self._filename_variants(photo)
        for payload, description, single_result_score in self._search_payloads(photo):
            candidates = self.immich_client.search_metadata(payload, description)
            candidates = self._filter_exact_filename(candidates, filename_variants)
            if not candidates:
                continue

            if len(candidates) == 1 and single_result_score > 0:
                logger.debug("Specific Immich search selected one candidate for %s via %s", photo.filename, description)
                return candidates, single_result_score

            best_candidate, best_score, tied_candidates = self._rank_candidates(photo, candidates)
            if best_candidate and best_score >= self.EXACT_TIMESTAMP_SCORE:
                return tied_candidates, best_score

            if best_score > best_weak_score:
                best_weak_candidates = tied_candidates or candidates
                best_weak_score = best_score

            logger.debug(
                "Immich search %s returned %s weak candidates for %s; relaxing query",
                description,
                len(candidates),
                photo.filename,
            )

        if best_weak_candidates:
            return best_weak_candidates, 0

        for filename in filename_variants:
            candidates = self.immich_client.search_by_filename(filename)
            candidates = self._filter_exact_filename(candidates, filename_variants)
            if candidates:
                return candidates, 0

        return [], 0

    def _search_payloads(self, photo: FavoritePhoto) -> list[tuple[dict, str, int]]:
        """Build a high-to-low specificity Immich search ladder."""
        payloads: list[tuple[dict, str, int]] = []

        for filename in self._filename_variants(photo):
            base_payload = {"originalFileName": filename}
            description_filename = filename if filename == photo.filename else f"{filename} variant"

            tight_date_payload = self._with_date_window(
                base_payload,
                photo.asset_date,
                timedelta(minutes=self.TIGHT_DATE_WINDOW_MINUTES),
            )
            broad_date_payload = self._with_date_window(
                base_payload,
                photo.asset_date,
                timedelta(days=self.date_tolerance_days),
            )

            if tight_date_payload:
                camera_payload = self._with_camera_filters(tight_date_payload, photo, include_lens=True)
                if camera_payload != tight_date_payload:
                    payloads.append(
                        (
                            camera_payload,
                            f"{description_filename} + tight date + camera/lens",
                            self.STRONG_MATCH_SCORE,
                        )
                    )

                payloads.append((tight_date_payload, f"{description_filename} + tight date", self.EXACT_TIMESTAMP_SCORE))

            if broad_date_payload and broad_date_payload != tight_date_payload:
                camera_payload = self._with_camera_filters(broad_date_payload, photo, include_lens=True)
                if camera_payload != broad_date_payload:
                    payloads.append(
                        (
                            camera_payload,
                            f"{description_filename} + broad date + camera/lens",
                            self.STRONG_MATCH_SCORE,
                        )
                    )

                payloads.append((broad_date_payload, f"{description_filename} + broad date", self.EXACT_TIMESTAMP_SCORE))

            camera_payload = self._with_camera_filters(base_payload, photo, include_lens=True)
            if camera_payload != base_payload:
                payloads.append((camera_payload, f"{description_filename} + camera/lens", self.STRONG_MATCH_SCORE))

            camera_payload = self._with_camera_filters(base_payload, photo, include_lens=False)
            if camera_payload != base_payload:
                payloads.append((camera_payload, f"{description_filename} + camera", self.STRONG_MATCH_SCORE))

        return self._dedupe_search_payloads(payloads)

    def _dedupe_search_payloads(self, payloads: list[tuple[dict, str, int]]) -> list[tuple[dict, str, int]]:
        """Remove duplicate payloads created by partial metadata."""
        seen: set[tuple[tuple[str, object], ...]] = set()
        unique_payloads = []

        for payload, description, score in payloads:
            key = tuple(sorted(payload.items()))
            if key in seen:
                continue

            seen.add(key)
            unique_payloads.append((payload, description, score))

        return unique_payloads

    def _with_date_window(
        self,
        payload: dict,
        asset_date: datetime | None,
        window: timedelta,
    ) -> dict | None:
        """Return payload plus Immich taken date bounds."""
        if asset_date is None:
            return None

        created_after = asset_date - window
        created_before = asset_date + window
        return {
            **payload,
            "takenAfter": created_after.isoformat(),
            "takenBefore": created_before.isoformat(),
        }

    def _with_camera_filters(self, payload: dict, photo: FavoritePhoto, include_lens: bool) -> dict:
        """Return payload plus supported Immich camera filters."""
        camera_payload = dict(payload)

        if photo.make:
            camera_payload["make"] = photo.make
        if photo.model:
            camera_payload["model"] = photo.model
        if include_lens and photo.lens_model:
            camera_payload["lensModel"] = photo.lens_model

        return camera_payload

    def _filter_exact_filename(self, candidates: list[ImmichAsset], filenames: list[str]) -> list[ImmichAsset]:
        """Keep only candidates whose original filename exactly matches.

        Args:
            candidates: List of candidate assets
            filenames: Expected filename variants

        Returns:
            Filtered list of candidates
        """
        for filename in filenames:
            case_sensitive_matches = [candidate for candidate in candidates if candidate.original_file_name == filename]
            if case_sensitive_matches:
                return case_sensitive_matches

        expected_casefolded = {filename.casefold() for filename in filenames}
        return [candidate for candidate in candidates if candidate.original_file_name.casefold() in expected_casefolded]

    def _filename_variants(self, photo: FavoritePhoto) -> list[str]:
        """Return known filename variants produced by Photos exports."""
        path = PurePath(photo.filename)
        stem = path.stem
        suffix = path.suffix
        variants = [photo.filename]

        if suffix:
            variants.append(f"{stem}-adjusted{suffix.upper()}")
            if photo.size:
                variants.append(f"{stem}-{photo.size}{suffix}")
                variants.append(f"{stem}-{photo.size}{suffix.upper()}")

        return list(dict.fromkeys(variants))

    def _enrich_candidates(self, candidates: list[ImmichAsset], force: bool = False) -> list[ImmichAsset]:
        """Fetch full Immich details only for narrowed candidate sets."""
        if len(candidates) <= 1 and not force:
            return candidates

        if len(candidates) > 3:
            logger.debug("Skipping enrichment for %s tied candidates", len(candidates))
            return candidates

        enriched = []
        for candidate in candidates:
            try:
                enriched.append(self.immich_client.get_asset(candidate.id))
            except Exception as e:
                logger.warning("Failed to enrich candidate %s: %s", candidate.id, e)
                enriched.append(candidate)

        return enriched

    def _rank_candidates(
        self,
        photo: FavoritePhoto,
        candidates: list[ImmichAsset],
    ) -> tuple[ImmichAsset | None, int, list[ImmichAsset]]:
        """Rank Immich candidates by metadata agreement with the source favorite."""
        scored_candidates = [(candidate, self._score_candidate(photo, candidate)) for candidate in candidates]
        if not scored_candidates:
            return None, 0, []

        scored_candidates.sort(key=lambda item: (-item[1], item[0].original_path or "", item[0].id))
        best_score = scored_candidates[0][1]
        best_candidates = [candidate for candidate, score in scored_candidates if score == best_score]
        return self._choose_deterministic_candidate(best_candidates), best_score, best_candidates

    def _score_candidate(self, photo: FavoritePhoto, candidate: ImmichAsset) -> int:
        """Score one Immich candidate against one source favorite."""
        score = 0

        score += self._score_best_date(photo, candidate)
        score += self._score_dimensions(photo.dimensions, candidate.width, candidate.height)
        score += self._score_file_size(photo.size, candidate.file_size_in_byte)
        score += self._score_path_date(photo.asset_date, candidate.original_path)
        score += self._score_location(photo.latitude, photo.longitude, candidate.latitude, candidate.longitude)
        score += self._score_camera(photo, candidate)

        return score

    def _score_best_date(self, photo: FavoritePhoto, candidate: ImmichAsset) -> int:
        """Score the best timestamp agreement across Immich date fields."""
        score = self._score_date(photo.asset_date, candidate.file_created_at)

        if candidate.local_date_time and candidate.local_date_time != candidate.file_created_at:
            score = max(score, self._score_date(photo.asset_date, candidate.local_date_time))

        if candidate.date_time_original and candidate.date_time_original != candidate.file_created_at:
            score = max(score, self._score_date(photo.asset_date, candidate.date_time_original))

        return score

    def _score_date(self, expected: datetime | None, actual: datetime | None) -> int:
        """Score timestamp agreement."""
        if not expected or not actual:
            return 0

        expected_normalized = expected.replace(tzinfo=None)
        actual_normalized = actual.replace(tzinfo=None)
        difference_seconds = abs((expected_normalized - actual_normalized).total_seconds())
        if difference_seconds <= 2:
            return 55
        if difference_seconds <= 60:
            return 45
        if expected_normalized.date() == actual_normalized.date():
            return 25

        return 0

    def _score_dimensions(
        self,
        expected: tuple[int, int] | None,
        width: int | None,
        height: int | None,
    ) -> int:
        """Score image dimension agreement."""
        if not expected or not width or not height:
            return 0

        expected_width, expected_height = expected
        if (expected_width, expected_height) == (width, height):
            return 20
        if (expected_width, expected_height) == (height, width):
            return 12

        return 0

    def _score_file_size(self, expected: int | None, actual: int | None) -> int:
        """Score file size agreement."""
        if not expected or not actual:
            return 0

        difference = abs(expected - actual)
        if difference == 0:
            return 35
        if difference <= 2048:
            return 18
        if difference / expected <= 0.01:
            return 10

        return 0

    def _score_path_date(self, expected: datetime | None, original_path: str | None) -> int:
        """Score agreement with the imported YYYY/MM/DD path."""
        if not expected or not original_path:
            return 0

        return 10 if expected.strftime("/%Y/%m/%d/") in original_path else 0

    def _score_location(
        self,
        expected_latitude: float | None,
        expected_longitude: float | None,
        actual_latitude: float | None,
        actual_longitude: float | None,
    ) -> int:
        """Score GPS agreement when both sources have coordinates."""
        if not all(value is not None for value in [
            expected_latitude,
            expected_longitude,
            actual_latitude,
            actual_longitude,
        ]):
            return 0

        lat_diff = abs(expected_latitude - actual_latitude)
        lon_diff = abs(expected_longitude - actual_longitude)
        if lat_diff <= 0.0001 and lon_diff <= 0.0001:
            return 20
        if lat_diff <= 0.001 and lon_diff <= 0.001:
            return 10

        return 0

    def _score_camera(self, photo: FavoritePhoto, candidate: ImmichAsset) -> int:
        """Score camera metadata agreement."""
        score = 0

        if photo.make and candidate.make and photo.make.casefold() == candidate.make.casefold():
            score += 5

        if photo.model and candidate.model and photo.model.casefold() == candidate.model.casefold():
            score += 5

        return score

    def _choose_deterministic_candidate(self, candidates: list[ImmichAsset]) -> ImmichAsset | None:
        """Choose one candidate deterministically from equivalent duplicates."""
        if not candidates:
            return None

        return sorted(candidates, key=lambda candidate: (candidate.original_path or "", candidate.id))[0]
