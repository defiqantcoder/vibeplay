import json
import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse

from vibeplay.db import get_connection
from vibeplay.desktop.settings import load_desktop_settings
from vibeplay.player import get_audio_file_technical_info, get_playback_status
from vibeplay.playlist import calculate_playlist_summary, calculate_transition_metrics
from vibeplay.web import get_filtered_tracks, get_library_clusters, load_saved_playlist

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index_page(request: Request) -> Response:
    """Render the main console dashboard shell."""
    active_desktop_settings = load_desktop_settings(request.app.state.cfg.get_desktop_settings_path(request.app.state.db_path))
    with get_connection(request.app.state.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(duration), 0) FROM tracks WHERE status = 'active'")
        count_row = cursor.fetchone()
        total_tracks = count_row[0] if count_row else 0
        total_duration = float(count_row[1]) if count_row else 0.0

        cursor.execute(
            """
            SELECT DISTINCT COALESCE(v.artist, t.artist) AS artist_name
            FROM tracks t
            LEFT JOIN v_tracks_best_value v ON t.id = v.track_id
            WHERE t.status = 'active' AND COALESCE(v.artist, t.artist) IS NOT NULL
            ORDER BY LOWER(COALESCE(v.artist, t.artist)) ASC
            """
        )
        artists = [r[0] for r in cursor.fetchall() if r[0]]
        tracks = get_filtered_tracks(conn, mood_threshold=request.app.state.cfg.mood_confidence_threshold)

        cursor.execute("SELECT id FROM playlists ORDER BY id DESC LIMIT 1")
        recent_pl = cursor.fetchone()

    latest_playlist = None
    if recent_pl:
        try:
            latest_playlist = load_saved_playlist(request.app.state.db_path, recent_pl[0])
        except Exception as err:
            logger.debug("Could not load recent playlist: %s", err)

    latest_transitions = calculate_transition_metrics(latest_playlist.tracks) if latest_playlist else []
    latest_summary = calculate_playlist_summary(latest_playlist.tracks, latest_transitions) if latest_playlist else {}

    clusters = get_library_clusters(request.app.state.db_path, request.app.state.cfg)
    playback = get_playback_status(request.app.state.db_path, request.app.state.cfg)

    selected_track = tracks[0] if tracks else None
    selected_tech_info = None
    selected_mood_scores: dict[str, float] = {}
    if selected_track:
        try:
            selected_tech_info = get_audio_file_technical_info(selected_track["path"])
        except Exception:
            selected_tech_info = None
        if selected_track.get("mood_scores"):
            try:
                selected_mood_scores = json.loads(selected_track["mood_scores"])
            except Exception:
                selected_mood_scores = {}
        for m in ("electronic", "relaxed", "acoustic", "party", "happy", "aggressive", "sad"):
            if m not in selected_mood_scores:
                selected_mood_scores[m] = 0.0

    return request.app.state.templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "total_tracks": total_tracks,
            "total_duration": total_duration,
            "total_clusters": len(clusters),
            "tracks": tracks,
            "artists": artists,
            "clusters": clusters,
            "playlist": latest_playlist,
            "transitions": latest_transitions,
            "summary": latest_summary,
            "active_step": 3 if latest_playlist else 1,
            "playback": playback,
            "desktop_settings": active_desktop_settings,
            "selected_track": selected_track,
            "selected_tech_info": selected_tech_info,
            "selected_mood_scores": selected_mood_scores,
        },
    )
