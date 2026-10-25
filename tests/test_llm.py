"""Tests for optional LLM integration layer.

Covers provider interface, Gemini/Ollama configuration, FakeLLMProvider,
prompt-to-plan translation with 5 diverse prompt fixtures, batch vibe tagging,
privacy redaction, SQLite prompt caching, validation retry, and CLI/Web integration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from vibeplay.cli import app
from vibeplay.config import Settings
from vibeplay.db import (
    get_connection,
    get_llm_cache,
    init_db,
    insert_or_replace_enrichment,
    insert_or_replace_features,
    insert_track,
)
from vibeplay.llm import (
    FakeLLMProvider,
    LLMProvider,
    OllamaProvider,
    PromptPlaylistPlan,
    batch_vibe_tag_tracks,
    compute_prompt_hash,
    get_llm_provider,
    parse_prompt_to_plan,
    sanitize_track_for_privacy,
)
from vibeplay.playlist import PlaylistRuleConfig, generate_playlist
from vibeplay.web import create_app

runner = CliRunner()


@pytest.fixture
def test_db_with_tracks(tmp_path: Path) -> tuple[Path, Settings]:
    """Create an initialized test database populated with sample tracks and features."""
    db_file = tmp_path / "vibeplay_llm_test.db"
    init_db(db_file)

    settings = Settings(
        db_path=db_file,
        llm_provider="fake",
        vector_cache_dir=tmp_path,
    )

    sample_tracks = [
        (
            1,
            "/music/ambient_rain.flac",
            "Midnight Rain",
            "Atmosphere Project",
            "Textures",
            70.0,
            0.20,
            0.30,
            -18.0,
            "C",
            "minor",
            {"relaxed": 0.9, "sad": 0.3},
        ),
        (
            2,
            "/music/workout_techno.flac",
            "Turbine",
            "Berlin Pulse",
            "Klang",
            135.0,
            0.88,
            0.85,
            -6.0,
            "G",
            "minor",
            {"party": 0.8, "electronic": 0.95},
        ),
        (
            3,
            "/music/acoustic_folk.flac",
            "Pine Needle Sunrise",
            "Woodland",
            "Cabin Songs",
            82.0,
            0.35,
            0.45,
            -14.0,
            "D",
            "major",
            {"acoustic": 0.95, "relaxed": 0.7},
        ),
        (
            4,
            "/music/melancholy_jazz.flac",
            "Blue in Autumn",
            "Miles Quartette",
            "Midnight Cafe",
            60.0,
            0.25,
            0.35,
            -16.0,
            "C",
            "minor",
            {"sad": 0.85, "relaxed": 0.7},
        ),
        (
            5,
            "/music/summer_disco.flac",
            "Rooftop Sunset",
            "Solar Groove",
            "Discotheque",
            124.0,
            0.80,
            0.90,
            -7.5,
            "A",
            "minor",
            {"party": 0.9, "happy": 0.85},
        ),
    ]

    import numpy as np

    with get_connection(db_file) as conn:
        for (
            tid,
            path,
            title,
            artist,
            album,
            bpm,
            energy,
            dance,
            loud,
            key,
            scale,
            moods,
        ) in sample_tracks:
            insert_track(
                conn=conn,
                path=path,
                mtime=1700000000.0,
                size=15000000,
                file_hash=f"hash_{tid}",
                duration=210.0,
                title=title,
                artist=artist,
                album=album,
            )
            emb = np.sin(np.linspace(0, tid, 128)).astype(np.float32)
            insert_or_replace_features(
                conn=conn,
                track_id=tid,
                analyzer_version="essentia_2.1",
                bpm=bpm,
                key=key,
                scale=scale,
                loudness=loud,
                danceability=dance,
                energy=energy,
                mood_scores_json=json.dumps(moods),
                embedding_blob=emb.tobytes(),
            )
            insert_or_replace_enrichment(
                conn=conn,
                track_id=tid,
                mb_recording_id=f"rec_{tid}",
                mb_release_id=f"rel_{tid}",
                mb_artist_id=f"art_{tid}",
                canonical_title=title,
                canonical_artist=artist,
                canonical_album_artist=artist,
                canonical_album=album,
                canonical_year=2023,
                canonical_track_no=1,
                canonical_track_total=10,
                canonical_disc_no=1,
                canonical_disc_total=1,
                genres=json.dumps(["Electronic" if energy > 0.6 else "Acoustic"]),
                tags=json.dumps(["audiophile", "lossless"]),
                confidence=0.95,
                status="matched",
                source="musicbrainz",
                raw_metadata="{}",
            )
        conn.commit()

    return db_file, settings


# ---------------------------------------------------------------------------
# Provider Interface & Factory Tests
# ---------------------------------------------------------------------------


def test_provider_factory_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that get_llm_provider correctly handles 'off', 'fake', 'ollama', and 'gemini'."""
    # 1. Default: off -> returns None
    off_settings = Settings(llm_provider="off")
    assert get_llm_provider(off_settings) is None

    # 2. Fake provider
    fake_settings = Settings(llm_provider="fake")
    provider = get_llm_provider(fake_settings)
    assert isinstance(provider, FakeLLMProvider)
    assert provider.model_name == "fake-model"

    # 3. Ollama provider
    ollama_settings = Settings(
        llm_provider="ollama",
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="llama3.2",
    )
    ollama_provider = get_llm_provider(ollama_settings)
    assert isinstance(ollama_provider, OllamaProvider)
    assert ollama_provider.base_url == "http://127.0.0.1:11434"
    assert ollama_provider.model_name == "llama3.2"

    # 4. Gemini without API key raises ValueError
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    gemini_no_key = Settings(_env_file=None, llm_provider="gemini", gemini_api_key=None)
    with pytest.raises(ValueError, match="Gemini API key is required"):
        get_llm_provider(gemini_no_key)


def test_fake_llm_provider_methods() -> None:
    """Verify FakeLLMProvider generate_text and generate_json methods."""
    provider = FakeLLMProvider(
        custom_responses={
            "custom prompt": "Hello from custom test prompt",
            "custom json": {"name": "Custom Session", "mode": "rules", "limit": 15},
        }
    )

    text_res = provider.generate_text("custom prompt")
    assert text_res == "Hello from custom test prompt"

    json_res = provider.generate_json("custom json")
    assert json_res["name"] == "Custom Session"
    assert json_res["limit"] == 15
    assert len(provider.call_history) == 2


# ---------------------------------------------------------------------------
# Caching & Retries Tests
# ---------------------------------------------------------------------------


def test_llm_cache_hit_and_miss(test_db_with_tracks: tuple[Path, Settings]) -> None:
    """Verify LLM caching in SQLite keyed by SHA256 of model:prompt."""
    db_file, settings = test_db_with_tracks
    provider = FakeLLMProvider()

    prompt = "rainy night focus, no vocals"
    model_name = provider.model_name
    expected_hash = compute_prompt_hash(model_name, prompt)

    # First call: cache miss, provider called
    plan1 = parse_prompt_to_plan(prompt, db_path=db_file, settings=settings, provider=provider)
    assert plan1.name == "Rainy Night Focus"
    assert len(provider.call_history) == 1

    # Verify cached in database
    with get_connection(db_file) as conn:
        cached_row = get_llm_cache(conn, expected_hash)
        assert cached_row is not None
        cached_data = json.loads(cached_row)
        assert cached_data["name"] == "Rainy Night Focus"

    # Second call: cache hit, provider NOT called again
    plan2 = parse_prompt_to_plan(prompt, db_path=db_file, settings=settings, provider=provider)
    assert plan2.name == "Rainy Night Focus"
    assert len(provider.call_history) == 1  # Still 1 call!


def test_pydantic_validation_retry_and_graceful_fallback(
    test_db_with_tracks: tuple[Path, Settings],
) -> None:
    """Verify that invalid output is retried once and fails gracefully on repeated error."""
    db_file, settings = test_db_with_tracks

    class FlakyProvider(LLMProvider):
        model_name = "flaky"
        call_count = 0

        def generate_text(self, prompt: str, system_instruction: str | None = None) -> str:
            return ""

        def generate_json(
            self,
            prompt: str,
            schema: type[Any] | None = None,
            system_instruction: str | None = None,
        ) -> dict[str, Any]:
            self.call_count += 1
            if self.call_count == 1:
                # Invalid schema output (invalid type that triggers ValidationError)
                return {"bpm_min": "INVALID_NOT_A_FLOAT"}
            # Second attempt succeeds
            return {
                "name": "Recovered Session",
                "description": "Recovered from retry.",
                "mode": "rules",
                "vibe": "chill",
            }

    provider = FlakyProvider()
    plan = parse_prompt_to_plan("chill vibes", db_path=db_file, settings=settings, provider=provider)
    assert provider.call_count == 2
    assert plan.name == "Recovered Session"


def test_graceful_fallback_when_retries_exhausted(
    test_db_with_tracks: tuple[Path, Settings],
) -> None:
    """Verify that when both initial call and retry fail, a heuristic plan is returned without crashing."""
    db_file, settings = test_db_with_tracks

    class BrokenProvider(LLMProvider):
        model_name = "broken"

        def generate_text(self, prompt: str, system_instruction: str | None = None) -> str:
            raise RuntimeError("Fatal provider outage")

        def generate_json(
            self,
            prompt: str,
            schema: type[Any] | None = None,
            system_instruction: str | None = None,
        ) -> dict[str, Any]:
            raise RuntimeError("Fatal provider outage")

    provider = BrokenProvider()
    plan = parse_prompt_to_plan("rainy night focus", db_path=db_file, settings=settings, provider=provider)
    assert plan is not None
    assert plan.name == "Rainy Night Focus"
    assert plan.vibe == "chill"


# ---------------------------------------------------------------------------
# Privacy & Batch Vibe Tagging Tests
# ---------------------------------------------------------------------------


def test_sanitize_track_for_privacy() -> None:
    """Strictly verify privacy: no audio data or file paths ever leave the machine."""
    unsafe_track = {
        "track_id": 42,
        "path": "/home/user/super_secret_directory/private_audio.flac",
        "artist": "Secret Artist",
        "title": "Private Track",
        "audio_bytes": b"RIFF....fake_wav_data",
        "waveform": [0.1, -0.2, 0.5],
        "bpm": 120.4,
        "energy": 0.75,
        "danceability": 0.62,
        "loudness": -9.2,
        "key": "A",
        "scale": "minor",
        "user_email": "user@example.com",
    }

    safe = sanitize_track_for_privacy(unsafe_track)

    assert "path" not in safe
    assert "audio_bytes" not in safe
    assert "waveform" not in safe
    assert "user_email" not in safe

    # Verify only safe scalar numbers and metadata are preserved
    assert safe["track_id"] == 42
    assert safe["artist"] == "Secret Artist"
    assert safe["title"] == "Private Track"
    assert safe["bpm"] == 120.4
    assert safe["energy"] == 0.75
    assert safe["danceability"] == 0.62
    assert safe["loudness"] == -9.2
    assert safe["key"] == "A"
    assert safe["scale"] == "minor"


def test_batch_vibe_tagging_execution(
    test_db_with_tracks: tuple[Path, Settings],
) -> None:
    """Verify batch vibe tagging updates SQLite database with tags and handles caching."""
    db_file, settings = test_db_with_tracks
    provider = FakeLLMProvider()

    tracks_to_tag = [
        {
            "track_id": 1,
            "title": "Midnight Rain",
            "artist": "Atmosphere Project",
            "bpm": 70.0,
            "energy": 0.20,
            "danceability": 0.30,
        },
        {
            "track_id": 2,
            "title": "Turbine",
            "artist": "Berlin Pulse",
            "bpm": 135.0,
            "energy": 0.88,
            "danceability": 0.85,
        },
    ]

    results = batch_vibe_tag_tracks(
        tracks=tracks_to_tag,
        db_path=db_file,
        settings=settings,
        provider=provider,
        batch_size=2,
    )

    assert len(results) == 2
    assert results[0].track_id == 1
    assert "chill" in results[0].mood_tags or "atmospheric" in results[0].mood_tags

    # Verify persisted in SQLite
    with get_connection(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT tags, genres FROM enrichment WHERE track_id = 1")
        row = cursor.fetchone()
        assert row is not None
        assert row["tags"] is not None


# ---------------------------------------------------------------------------
# Requirement Check: Five Diverse Prompts Match Intent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt,expected_vibe,expected_max_energy,expected_min_energy,expected_max_bpm,expected_min_bpm",
    [
        # Prompt 1: rainy night focus, no vocals
        ("rainy night focus, no vocals", "chill", 0.50, None, 110.0, None),
        # Prompt 2: high-energy workout techno
        ("high-energy workout techno", "workout", None, 0.70, None, 120.0),
        # Prompt 3: acoustic campfire morning
        ("acoustic campfire morning", "acoustic", 0.65, None, None, None),
        # Prompt 4: late night melancholy jazz
        ("late night melancholy jazz", "melancholy", 0.55, None, None, None),
        # Prompt 5: summer rooftop party
        ("summer rooftop party", "party", None, 0.60, None, 110.0),
    ],
)
def test_five_prompts_match_intent(
    test_db_with_tracks: tuple[Path, Settings],
    prompt: str,
    expected_vibe: str,
    expected_max_energy: float | None,
    expected_min_energy: float | None,
    expected_max_bpm: float | None,
    expected_min_bpm: float | None,
) -> None:
    """Verify that five diverse natural language prompts parse into intent-matching acoustic filters."""
    db_file, settings = test_db_with_tracks
    provider = FakeLLMProvider()

    plan = parse_prompt_to_plan(prompt, db_path=db_file, settings=settings, provider=provider)

    assert isinstance(plan, PromptPlaylistPlan)
    assert len(plan.name) > 0
    assert len(plan.description) > 0

    # Check vibe preset matching
    if expected_vibe is not None:
        assert plan.vibe == expected_vibe

    # Check energy constraint matching
    if expected_max_energy is not None and plan.energy_max is not None:
        assert plan.energy_max <= expected_max_energy

    if expected_min_energy is not None and plan.energy_min is not None:
        assert plan.energy_min >= expected_min_energy

    # Check BPM constraint matching
    if expected_max_bpm is not None and plan.bpm_max is not None:
        assert plan.bpm_max <= expected_max_bpm

    if expected_min_bpm is not None and plan.bpm_min is not None:
        assert plan.bpm_min >= expected_min_bpm

    # Verify playlist engine successfully consumes the generated plan
    rules = PlaylistRuleConfig(
        mode=plan.mode,
        arc=plan.arc,
        vibe=plan.vibe,
        bpm_min=plan.bpm_min,
        bpm_max=plan.bpm_max,
        energy_min=plan.energy_min,
        energy_max=plan.energy_max,
        danceability_min=plan.danceability_min,
        danceability_max=plan.danceability_max,
        mood_min=plan.mood_min,
        genre_include=plan.genre_include,
        genre_exclude=plan.genre_exclude,
        limit=plan.limit,
    )

    playlist = generate_playlist(
        db_path=db_file,
        name=plan.name,
        rules=rules,
        description=plan.description,
        settings=settings,
    )

    assert playlist.playlist_id > 0
    assert playlist.name == plan.name
    assert playlist.description == plan.description
    assert len(playlist.tracks) > 0


# ---------------------------------------------------------------------------
# CLI Integration Tests
# ---------------------------------------------------------------------------


def test_cli_playlist_with_prompt(test_db_with_tracks: tuple[Path, Settings], monkeypatch: Any) -> None:
    """Test 'vibeplay playlist --prompt ...' through the CLI."""
    db_file, settings = test_db_with_tracks
    monkeypatch.setattr("vibeplay.cli.get_settings", lambda: settings)

    res = runner.invoke(
        app,
        [
            "playlist",
            "--prompt",
            "rainy night focus, no vocals",
            "--db",
            str(db_file),
        ],
    )

    assert res.exit_code == 0
    assert "AI Vibe Planner" in res.stdout
    assert "Rainy Night Focus" in res.stdout
    assert "Playlist Saved" in res.stdout


def test_cli_tag_command(test_db_with_tracks: tuple[Path, Settings], monkeypatch: Any) -> None:
    """Test 'vibeplay tag --all' through the CLI."""
    db_file, settings = test_db_with_tracks
    monkeypatch.setattr("vibeplay.cli.get_settings", lambda: settings)

    res = runner.invoke(
        app,
        [
            "tag",
            "--all",
            "--db",
            str(db_file),
        ],
    )

    assert res.exit_code == 0
    assert "Batch Vibe Tagging" in res.stdout
    assert "Vibe Tagging Results" in res.stdout
    assert "Successfully tagged" in res.stdout


# ---------------------------------------------------------------------------
# Web UI Endpoint Tests
# ---------------------------------------------------------------------------


def test_web_api_generate_playlist_with_prompt(
    test_db_with_tracks: tuple[Path, Settings],
) -> None:
    """Verify that POST /api/playlist/generate with prompt generates thematic playlist and renders HTML."""
    from fastapi.testclient import TestClient

    db_file, settings = test_db_with_tracks
    app_instance = create_app(db_path=db_file, settings=settings)
    client = TestClient(app_instance)

    response = client.post(
        "/api/playlist/generate",
        data={
            "prompt": "high-energy workout techno",
            "limit": "5",
        },
    )

    assert response.status_code == 200
    html = response.text
    assert "High-Energy Workout Techno" in html
    assert "builder-tracks-container" in html
    assert "Play in MPD" in html
    assert "Export M3U8" in html
