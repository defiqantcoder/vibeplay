"""Optional LLM integration layer for vibeplay.

Provides provider abstraction (Gemini, Ollama, Fake), natural language
playlist prompt parsing to Pydantic filter rules, batch vibe tagging,
privacy redaction, SQLite prompt caching, and exponential backoff.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, TypeVar

import httpx
from pydantic import BaseModel, Field, ValidationError

from vibeplay.config import Settings, get_settings
from vibeplay.db import (
    get_connection,
    get_llm_cache,
    set_llm_cache,
    update_track_vibe_tags,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

PLAYLIST_SYSTEM_INSTRUCTION = """
You are an expert audiophile and DJ curator for the vibeplay music player.
Your task is to translate a user's natural language vibe or playlist prompt into a structured playlist specification.
You must NEVER select specific audio tracks or filenames. You only define the thematic title, one-line description, and acoustic filter parameters:
- name: A creative, evocative, thematic title for the playlist.
- description: A concise one-sentence description explaining the mood and listening experience.
- mode: "rules" or "arc". Use "arc" if the prompt implies an energy journey or progression.
- arc: Energy trajectory if mode is "arc" ('ramp_up', 'cooldown', 'peak', 'steady').
- vibe: Optional preset ('chill', 'party', 'acoustic', 'electronic', 'workout', 'melancholy').
- bpm_min, bpm_max: Tempo bounds in BPM (40 to 220).
- energy_min, energy_max: Energy bounds (0.0 to 1.0).
- danceability_min, danceability_max: Danceability bounds (0.0 to 1.0).
- mood_min: Dict of minimum mood scores, e.g. {"relaxed": 0.4, "acoustic": 0.5}. Supported moods: relaxed, happy, sad, party, aggressive, acoustic, electronic.
- genre_include: List of genres to include.
- genre_exclude: List of genres to exclude.
- limit: Number of tracks (default 25).
"""

VIBE_TAGGING_SYSTEM_INSTRUCTION = """
You are an expert music archivist and acoustic metadata tagger.
Given a batch of musical tracks with artist, title, and scalar acoustic feature numbers (BPM, energy, danceability, loudness, key, scale), generate concise mood tags (e.g. relaxed, euphoric, dark, melancholic, ethereal, aggressive) and genre tags for each track.
Output valid JSON containing a 'tracks' array of objects with 'track_id', 'mood_tags', and 'genre_tags'.
"""


# ---------------------------------------------------------------------------
# Pydantic Output Schemas
# ---------------------------------------------------------------------------


class PromptPlaylistPlan(BaseModel):
    """Structured plan for rule-based playlist generation derived from a natural language prompt."""

    name: str = Field(
        default="Vibe Session",
        description="Thematic name for the playlist",
    )
    description: str = Field(
        default="Cohesive audio sequence matching prompt vibe.",
        description="One-line summary description of the playlist",
    )
    mode: str = Field(
        default="rules",
        description="Playlist mode: 'rules' or 'arc'",
    )
    arc: str | None = Field(
        default=None,
        description="Energy curve: 'ramp_up', 'cooldown', 'peak', 'steady'",
    )
    vibe: str | None = Field(
        default=None,
        description="Preset vibe if applicable: 'chill', 'party', 'acoustic', 'electronic', 'workout', 'melancholy'",
    )
    bpm_min: float | None = Field(default=None, description="Minimum tempo in BPM")
    bpm_max: float | None = Field(default=None, description="Maximum tempo in BPM")
    energy_min: float | None = Field(
        default=None, description="Minimum energy level [0.0, 1.0]"
    )
    energy_max: float | None = Field(
        default=None, description="Maximum energy level [0.0, 1.0]"
    )
    danceability_min: float | None = Field(
        default=None, description="Minimum danceability [0.0, 1.0]"
    )
    danceability_max: float | None = Field(
        default=None, description="Maximum danceability [0.0, 1.0]"
    )
    mood_min: dict[str, float] = Field(
        default_factory=dict,
        description="Minimum thresholds for mood probabilities",
    )
    genre_include: list[str] = Field(
        default_factory=list, description="Genres to include"
    )
    genre_exclude: list[str] = Field(
        default_factory=list, description="Genres to exclude"
    )
    limit: int = Field(default=25, description="Target playlist track count")


class TrackVibeTag(BaseModel):
    """Generated mood and genre tags for a single track."""

    track_id: int = Field(description="Database track ID")
    mood_tags: list[str] = Field(
        default_factory=list, description="Descriptive mood tags"
    )
    genre_tags: list[str] = Field(
        default_factory=list, description="Descriptive genre tags"
    )


class BatchVibeTagResponse(BaseModel):
    """Batch response container for track vibe tagging."""

    tracks: list[TrackVibeTag] = Field(
        default_factory=list, description="List of tagged tracks"
    )


# ---------------------------------------------------------------------------
# LLM Provider Abstract Interface
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract interface for LLM provider implementations."""

    model_name: str

    @abstractmethod
    def generate_text(
        self, prompt: str, system_instruction: str | None = None
    ) -> str:
        """Generate raw text response from prompt."""
        ...

    @abstractmethod
    def generate_json(
        self,
        prompt: str,
        schema: type[T] | None = None,
        system_instruction: str | None = None,
    ) -> dict[str, Any]:
        """Generate structured JSON response matching schema or returning dict."""
        ...


# ---------------------------------------------------------------------------
# Gemini Provider Implementation (google-genai SDK)
# ---------------------------------------------------------------------------


class GeminiProvider(LLMProvider):
    """LLM provider using Google Gemini via the official google-genai SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-3.8-flash",
        max_retries: int = 3,
        backoff_factor: float = 2.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Gemini API key is required. Set GEMINI_API_KEY environment variable "
                "or configure gemini_api_key in settings."
            )
        self.model_name = model_name
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        # Import google-genai lazily
        from google import genai

        self.client = genai.Client(api_key=self.api_key)

    def _execute_with_retry(self, action: Callable[[], Any]) -> Any:
        """Execute client call with exponential backoff on transient errors."""
        delay = 1.0
        for attempt in range(self.max_retries):
            try:
                return action()
            except Exception as err:
                if attempt == self.max_retries - 1:
                    logger.error(
                        "Gemini request failed after %d attempts: %s",
                        self.max_retries,
                        err,
                    )
                    raise
                logger.warning(
                    "Gemini request error (attempt %d/%d): %s; backing off %.1fs",
                    attempt + 1,
                    self.max_retries,
                    err,
                    delay,
                )
                time.sleep(delay)
                delay *= self.backoff_factor

    def generate_text(
        self, prompt: str, system_instruction: str | None = None
    ) -> str:
        """Generate text using Gemini."""
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system_instruction
        )

        def call() -> str:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config,
            )
            return response.text or ""

        return str(self._execute_with_retry(call))

    def generate_json(
        self,
        prompt: str,
        schema: type[T] | None = None,
        system_instruction: str | None = None,
    ) -> dict[str, Any]:
        """Generate JSON using Gemini structured output."""
        from google.genai import types

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema() if schema else None,
            system_instruction=system_instruction,
        )

        def call() -> dict[str, Any]:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config,
            )
            raw_text = (response.text or "").strip()
            # Clean possible markdown fence blocks if present
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw_text = "\n".join(lines).strip()
            return json.loads(raw_text)

        return self._execute_with_retry(call)


# ---------------------------------------------------------------------------
# Ollama Provider Implementation (local HTTP daemon)
# ---------------------------------------------------------------------------


class OllamaProvider(LLMProvider):
    """LLM provider using a local Ollama server over HTTP."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model_name: str = "llama3.2",
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    def _execute_with_retry(self, action: Callable[[], Any]) -> Any:
        """Execute Ollama HTTP request with exponential backoff."""
        delay = 1.0
        for attempt in range(self.max_retries):
            try:
                return action()
            except Exception as err:
                if attempt == self.max_retries - 1:
                    logger.error(
                        "Ollama request failed after %d attempts: %s",
                        self.max_retries,
                        err,
                    )
                    raise
                logger.warning(
                    "Ollama request error (attempt %d/%d): %s; backing off %.1fs",
                    attempt + 1,
                    self.max_retries,
                    err,
                    delay,
                )
                time.sleep(delay)
                delay *= self.backoff_factor

    def generate_text(
        self, prompt: str, system_instruction: str | None = None
    ) -> str:
        """Generate text using Ollama chat endpoint."""
        messages: list[dict[str, str]] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
        }

        def call() -> str:
            with httpx.Client(
                base_url=self.base_url, timeout=self.timeout
            ) as client:
                res = client.post("/api/chat", json=payload)
                res.raise_for_status()
                data = res.json()
                return data.get("message", {}).get("content", "")

        return str(self._execute_with_retry(call))

    def generate_json(
        self,
        prompt: str,
        schema: type[T] | None = None,
        system_instruction: str | None = None,
    ) -> dict[str, Any]:
        """Generate JSON using Ollama chat endpoint with format='json'."""
        messages: list[dict[str, str]] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "format": schema.model_json_schema() if schema else "json",
            "stream": False,
        }

        def call() -> dict[str, Any]:
            with httpx.Client(
                base_url=self.base_url, timeout=self.timeout
            ) as client:
                res = client.post("/api/chat", json=payload)
                res.raise_for_status()
                data = res.json()
                content = data.get("message", {}).get("content", "").strip()
                if content.startswith("```"):
                    lines = content.splitlines()
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    content = "\n".join(lines).strip()
                return json.loads(content)

        return self._execute_with_retry(call)


# ---------------------------------------------------------------------------
# Fake LLM Provider (for Unit Tests and Offline Simulations)
# ---------------------------------------------------------------------------


class FakeLLMProvider(LLMProvider):
    """Deterministic mock provider for unit tests and offline testing."""

    def __init__(
        self,
        model_name: str = "fake-model",
        custom_responses: dict[str, Any] | None = None,
        fail_count: int = 0,
    ) -> None:
        self.model_name = model_name
        self.custom_responses = custom_responses or {}
        self.call_history: list[dict[str, Any]] = []
        self.fail_count = fail_count

    def generate_text(
        self, prompt: str, system_instruction: str | None = None
    ) -> str:
        """Return pre-configured text response."""
        self.call_history.append(
            {
                "type": "text",
                "prompt": prompt,
                "system_instruction": system_instruction,
            }
        )
        if self.fail_count > 0:
            self.fail_count -= 1
            raise RuntimeError("Simulated transient rate limit error")
        return self.custom_responses.get(
            prompt, "Simulated LLM text response for vibeplay."
        )

    def generate_json(
        self,
        prompt: str,
        schema: type[T] | None = None,
        system_instruction: str | None = None,
    ) -> dict[str, Any]:
        """Return pre-configured or keyword-inferred JSON response."""
        self.call_history.append(
            {
                "type": "json",
                "prompt": prompt,
                "schema": schema.__name__ if schema else None,
                "system_instruction": system_instruction,
            }
        )
        if self.fail_count > 0:
            self.fail_count -= 1
            raise RuntimeError("Simulated transient rate limit error")

        if prompt in self.custom_responses:
            val = self.custom_responses[prompt]
            if isinstance(val, str):
                return json.loads(val)
            return val

        # Check if batch tagging prompt or schema is BatchVibeTagResponse
        lower = prompt.lower()
        if (
            schema is BatchVibeTagResponse
            or "tag the following" in lower
            or "mood_tags" in lower
            or ("tracks" in lower and "track_id" in lower)
        ):
            track_ids: list[int] = []
            if "{" in prompt:
                try:
                    json_part = prompt[prompt.index("{") : prompt.rindex("}") + 1]
                    data = json.loads(json_part)
                    for t in data.get("tracks", []):
                        track_ids.append(int(t.get("track_id") or t.get("id") or 0))
                except Exception:
                    pass
            if not track_ids:
                track_ids = [1, 2]
            return {
                "tracks": [
                    {
                        "track_id": tid,
                        "mood_tags": ["chill", "atmospheric"],
                        "genre_tags": ["Electronic", "Downtempo"],
                    }
                    for tid in track_ids
                ]
            }

        # Smart default mock responses based on intent keywords
        if "rainy" in lower or "focus" in lower:
            return {
                "name": "Rainy Night Focus",
                "description": "Introspective downtempo and acoustic textures for deep concentration.",
                "mode": "rules",
                "arc": "steady",
                "vibe": "chill",
                "bpm_min": 60.0,
                "bpm_max": 105.0,
                "energy_min": 0.1,
                "energy_max": 0.45,
                "danceability_min": 0.1,
                "danceability_max": 0.55,
                "mood_min": {"relaxed": 0.4},
                "genre_include": ["Ambient", "Acoustic", "Downtempo"],
                "genre_exclude": ["Metal", "Hardcore"],
                "limit": 20,
            }
        elif "workout" in lower or "techno" in lower:
            return {
                "name": "High-Energy Workout Techno",
                "description": "Driving electronic rhythms and peak tempo for intense training sessions.",
                "mode": "rules",
                "arc": "steady",
                "vibe": "workout",
                "bpm_min": 125.0,
                "bpm_max": 145.0,
                "energy_min": 0.75,
                "energy_max": 1.0,
                "danceability_min": 0.65,
                "danceability_max": 1.0,
                "mood_min": {"electronic": 0.5},
                "genre_include": ["Techno", "Electronic"],
                "genre_exclude": ["Acoustic", "Folk"],
                "limit": 25,
            }
        elif "campfire" in lower or "acoustic" in lower:
            return {
                "name": "Acoustic Campfire Morning",
                "description": "Warm acoustic guitars and gentle organic melodies for morning reflection.",
                "mode": "rules",
                "arc": "steady",
                "vibe": "acoustic",
                "bpm_min": 70.0,
                "bpm_max": 115.0,
                "energy_min": 0.15,
                "energy_max": 0.55,
                "danceability_min": 0.2,
                "danceability_max": 0.6,
                "mood_min": {"acoustic": 0.5},
                "genre_include": ["Folk", "Acoustic"],
                "genre_exclude": ["Electronic", "Techno"],
                "limit": 20,
            }
        elif "jazz" in lower or "melancholy" in lower:
            return {
                "name": "Late Night Melancholy Jazz",
                "description": "Smoky brass, quiet brushes, and contemplative blues for late hours.",
                "mode": "rules",
                "arc": "steady",
                "vibe": "melancholy",
                "bpm_min": 50.0,
                "bpm_max": 95.0,
                "energy_min": 0.1,
                "energy_max": 0.48,
                "danceability_min": 0.2,
                "danceability_max": 0.5,
                "mood_min": {"sad": 0.4},
                "genre_include": ["Jazz", "Blues"],
                "genre_exclude": ["Pop", "EDM"],
                "limit": 20,
            }
        elif "rooftop" in lower or "party" in lower:
            return {
                "name": "Summer Rooftop Party",
                "description": "Sun-soaked dance grooves and uplifting party energy.",
                "mode": "rules",
                "arc": "peak",
                "vibe": "party",
                "bpm_min": 115.0,
                "bpm_max": 130.0,
                "energy_min": 0.65,
                "energy_max": 0.95,
                "danceability_min": 0.65,
                "danceability_max": 1.0,
                "mood_min": {"party": 0.45},
                "genre_include": ["House", "Disco", "Pop"],
                "genre_exclude": ["Ambient"],
                "limit": 25,
            }

        # Generic fallback
        return {
            "name": "Eclectic Vibe Session",
            "description": "A thoughtfully curated listening session.",
            "mode": "rules",
            "arc": "steady",
            "vibe": None,
            "bpm_min": None,
            "bpm_max": None,
            "energy_min": None,
            "energy_max": None,
            "danceability_min": None,
            "danceability_max": None,
            "mood_min": {},
            "genre_include": [],
            "genre_exclude": [],
            "limit": 25,
        }


# ---------------------------------------------------------------------------
# Factory & Helpers
# ---------------------------------------------------------------------------


def get_llm_provider(settings: Settings | None = None) -> LLMProvider | None:
    """Instantiate and return the configured LLM provider.

    Args:
        settings: Application settings (defaults to loaded settings).

    Returns:
        LLMProvider | None: Configured provider instance, or None if provider is 'off'.
    """
    cfg = settings or get_settings()
    provider_type = (cfg.llm_provider or "off").lower().strip()

    if provider_type == "off":
        return None
    elif provider_type == "gemini":
        return GeminiProvider(
            api_key=cfg.gemini_api_key,
            model_name=cfg.llm_model,
        )
    elif provider_type == "ollama":
        return OllamaProvider(
            base_url=cfg.ollama_base_url,
            model_name=cfg.ollama_model,
        )
    elif provider_type == "fake":
        return FakeLLMProvider(model_name="fake-model")
    else:
        logger.warning(
            "Unknown llm_provider '%s'; falling back to None", provider_type
        )
        return None


def compute_prompt_hash(model: str, prompt: str) -> str:
    """Compute deterministic SHA256 cache key for an LLM prompt and model."""
    key_bytes = f"{model}:{prompt}".encode("utf-8")
    return hashlib.sha256(key_bytes).hexdigest()


# ---------------------------------------------------------------------------
# Core Features: Prompt-to-Plan & Batch Vibe Tagging
# ---------------------------------------------------------------------------


def parse_prompt_to_plan(
    prompt: str,
    db_path: Path,
    settings: Settings | None = None,
    provider: LLMProvider | None = None,
) -> PromptPlaylistPlan:
    """Convert natural language playlist prompt into validated PromptPlaylistPlan.

    The LLM translates listener intent into numeric bounds and vibe targets,
    never choosing tracks directly. Results are cached in SQLite.

    Args:
        prompt: User's natural language request (e.g. 'rainy night focus, no vocals').
        db_path: Path to SQLite database for cache storage.
        settings: Application settings.
        provider: Explicit LLMProvider instance (defaults to get_llm_provider()).

    Returns:
        PromptPlaylistPlan: Validated playlist configuration plan.
    """
    cfg = settings or get_settings()
    active_provider = (
        provider if provider is not None else get_llm_provider(cfg)
    )

    clean_prompt = prompt.strip()
    if not clean_prompt:
        return PromptPlaylistPlan(
            name="Vibe Session",
            description="Default playlist session.",
            mode="rules",
        )

    # If LLM is disabled or unavailable, provide an offline rule mapping
    if active_provider is None:
        logger.info(
            "LLM provider is off; falling back to keyword heuristics for prompt '%s'",
            clean_prompt,
        )
        return _fallback_keyword_plan(clean_prompt)

    model_name = active_provider.model_name
    prompt_hash = compute_prompt_hash(model_name, clean_prompt)

    # 1. Check cache
    with get_connection(db_path) as conn:
        cached_json = get_llm_cache(conn, prompt_hash)
        if cached_json:
            logger.info(
                "LLM cache hit for prompt '%s' (hash: %s)",
                clean_prompt,
                prompt_hash[:8],
            )
            try:
                data = json.loads(cached_json)
                return PromptPlaylistPlan.model_validate(data)
            except Exception as err:
                logger.warning(
                    "Cached JSON invalid (%s); refreshing from provider", err
                )

    # 2. Call provider with validation and single retry
    user_query = f"User Request: {clean_prompt}"
    plan_dict: dict[str, Any] | None = None

    try:
        raw_dict = active_provider.generate_json(
            prompt=user_query,
            schema=PromptPlaylistPlan,
            system_instruction=PLAYLIST_SYSTEM_INSTRUCTION,
        )
        plan = PromptPlaylistPlan.model_validate(raw_dict)
        plan_dict = plan.model_dump()
    except (ValidationError, json.JSONDecodeError, Exception) as first_err:
        logger.warning(
            "First LLM JSON generation failed (%s); retrying once...", first_err
        )
        try:
            retry_prompt = (
                f"{user_query}\n\nIMPORTANT: Return strictly valid JSON adhering "
                f"to the required schema without comments or markdown text."
            )
            raw_dict = active_provider.generate_json(
                prompt=retry_prompt,
                schema=PromptPlaylistPlan,
                system_instruction=PLAYLIST_SYSTEM_INSTRUCTION,
            )
            plan = PromptPlaylistPlan.model_validate(raw_dict)
            plan_dict = plan.model_dump()
        except Exception as retry_err:
            logger.error(
                "LLM retry failed (%s); gracefully falling back to heuristic plan.",
                retry_err,
            )
            return _fallback_keyword_plan(clean_prompt)

    # 3. Store valid response in cache
    if plan_dict is not None:
        with get_connection(db_path) as conn:
            set_llm_cache(
                conn=conn,
                prompt_hash=prompt_hash,
                prompt=clean_prompt,
                response=json.dumps(plan_dict),
                model=model_name,
            )
            conn.commit()

        return PromptPlaylistPlan.model_validate(plan_dict)

    return _fallback_keyword_plan(clean_prompt)


def _fallback_keyword_plan(prompt: str) -> PromptPlaylistPlan:
    """Generate a fallback plan using simple keyword matching when LLM is unavailable."""
    lower = prompt.lower()
    if "chill" in lower or "rain" in lower or "relax" in lower:
        return PromptPlaylistPlan(
            name="Rainy Night Focus",
            description="Calm, introspective audio textures for focus and relaxation.",
            mode="rules",
            vibe="chill",
            energy_max=0.50,
            bpm_max=110.0,
        )
    elif (
        "workout" in lower
        or "run" in lower
        or "gym" in lower
        or "techno" in lower
    ):
        return PromptPlaylistPlan(
            name="High-Energy Workout",
            description="Driving tempo and intense rhythm to power physical exercise.",
            mode="rules",
            vibe="workout",
            energy_min=0.70,
            bpm_min=120.0,
        )
    elif "party" in lower or "dance" in lower or "club" in lower:
        return PromptPlaylistPlan(
            name="Party Beats",
            description="High danceability and celebratory energy for gatherings.",
            mode="rules",
            vibe="party",
            danceability_min=0.65,
            energy_min=0.60,
        )
    elif "acoustic" in lower or "folk" in lower or "campfire" in lower:
        return PromptPlaylistPlan(
            name="Acoustic Session",
            description="Warm timbre and acoustic instrumentation.",
            mode="rules",
            vibe="acoustic",
            energy_max=0.60,
        )
    elif "melancholy" in lower or "sad" in lower or "blues" in lower:
        return PromptPlaylistPlan(
            name="Melancholy Evening",
            description="Reflective, somber melodies and moody dynamics.",
            mode="rules",
            vibe="melancholy",
            energy_max=0.50,
        )

    # General fallback
    return PromptPlaylistPlan(
        name="Vibe Selection",
        description=f"Playlist inspired by: '{prompt}'.",
        mode="rules",
    )


def sanitize_track_for_privacy(track: dict[str, Any]) -> dict[str, Any]:
    """Strip all file paths and raw audio data, retaining only metadata and scalar numbers.

    Strict privacy enforcement: never sends local file paths, audio waveforms,
    or user system directory details to any external or local LLM.

    Args:
        track: Raw track dictionary from database or scanner.

    Returns:
        dict[str, Any]: Privacy-safe dictionary with only artist, title, and scalar features.
    """
    raw_id = track.get("track_id") or track.get("id") or 0
    return {
        "track_id": int(raw_id),
        "artist": str(
            track.get("artist") or track.get("original_artist") or "Unknown"
        ),
        "title": str(
            track.get("title") or track.get("original_title") or "Unknown"
        ),
        "bpm": round(float(track["bpm"]), 1)
        if track.get("bpm") is not None
        else None,
        "energy": round(float(track["energy"]), 3)
        if track.get("energy") is not None
        else None,
        "danceability": round(float(track["danceability"]), 3)
        if track.get("danceability") is not None
        else None,
        "loudness": round(float(track["loudness"]), 1)
        if track.get("loudness") is not None
        else None,
        "key": str(track["key"]) if track.get("key") else None,
        "scale": str(track["scale"]) if track.get("scale") else None,
    }


def batch_vibe_tag_tracks(
    tracks: list[dict[str, Any]],
    db_path: Path,
    settings: Settings | None = None,
    provider: LLMProvider | None = None,
    batch_size: int = 20,
) -> list[TrackVibeTag]:
    """Batch-tag audio tracks with mood and genre descriptors using an LLM.

    Strictly complies with user privacy: sends only track title, artist, and
    scalar audio feature numbers. Caches each request/response in llm_cache.
    Persists resulting tags to the database.

    Args:
        tracks: List of track feature dictionaries.
        db_path: Path to SQLite database.
        settings: Application settings.
        provider: LLM provider instance.
        batch_size: Number of tracks per request to optimize batching.

    Returns:
        list[TrackVibeTag]: Generated tags for each processed track.
    """
    cfg = settings or get_settings()
    active_provider = (
        provider if provider is not None else get_llm_provider(cfg)
    )

    if not tracks:
        return []

    if active_provider is None:
        logger.warning(
            "LLM provider is off; cannot perform batch vibe tagging."
        )
        return []

    # 1. Sanitize all tracks for privacy
    safe_tracks = [sanitize_track_for_privacy(t) for t in tracks]
    all_results: list[TrackVibeTag] = []

    # 2. Process in batches
    for i in range(0, len(safe_tracks), batch_size):
        batch = safe_tracks[i : i + batch_size]
        batch_json_input = json.dumps({"tracks": batch}, sort_keys=True)
        prompt_hash = compute_prompt_hash(
            active_provider.model_name, batch_json_input
        )

        batch_response_dict: dict[str, Any] | None = None

        # Check cache
        with get_connection(db_path) as conn:
            cached = get_llm_cache(conn, prompt_hash)
            if cached:
                logger.info(
                    "LLM cache hit for vibe tagging batch %d-%d",
                    i,
                    i + len(batch),
                )
                try:
                    data = json.loads(cached)
                    resp = BatchVibeTagResponse.model_validate(data)
                    batch_response_dict = resp.model_dump()
                except Exception as err:
                    logger.warning("Invalid cached batch tag JSON: %s", err)

        # Call provider if not cached
        if batch_response_dict is None:
            user_prompt = (
                f"Tag the following musical tracks with mood and genre tags based on their title, "
                f"artist, and acoustic measurements:\n\n{batch_json_input}"
            )
            try:
                raw_dict = active_provider.generate_json(
                    prompt=user_prompt,
                    schema=BatchVibeTagResponse,
                    system_instruction=VIBE_TAGGING_SYSTEM_INSTRUCTION,
                )
                resp = BatchVibeTagResponse.model_validate(raw_dict)
                batch_response_dict = resp.model_dump()
            except (ValidationError, json.JSONDecodeError, Exception) as err:
                logger.warning(
                    "First attempt batch vibe tagging failed (%s); retrying once...",
                    err,
                )
                try:
                    raw_dict = active_provider.generate_json(
                        prompt=f"{user_prompt}\n\nSTRICT JSON ONLY conforming to schema.",
                        schema=BatchVibeTagResponse,
                        system_instruction=VIBE_TAGGING_SYSTEM_INSTRUCTION,
                    )
                    resp = BatchVibeTagResponse.model_validate(raw_dict)
                    batch_response_dict = resp.model_dump()
                except Exception as retry_err:
                    logger.error(
                        "Batch vibe tagging retry failed: %s; skipping batch",
                        retry_err,
                    )
                    continue

            # Store in cache
            if batch_response_dict is not None:
                with get_connection(db_path) as conn:
                    set_llm_cache(
                        conn=conn,
                        prompt_hash=prompt_hash,
                        prompt=batch_json_input,
                        response=json.dumps(batch_response_dict),
                        model=active_provider.model_name,
                    )
                    conn.commit()

        # Update database with tags
        if batch_response_dict:
            tags_resp = BatchVibeTagResponse.model_validate(batch_response_dict)
            with get_connection(db_path) as conn:
                for item in tags_resp.tracks:
                    update_track_vibe_tags(
                        conn=conn,
                        track_id=item.track_id,
                        mood_tags=item.mood_tags,
                        genre_tags=item.genre_tags,
                    )
                    all_results.append(item)
                conn.commit()

    return all_results
