from unittest.mock import Mock

from vibeplay.scanner import _detect_cover_art, _parse_first_string, _parse_int_pair, _parse_year


def test_parse_int_pair_odd_formats():
    assert _parse_int_pair("6/12") == (6, 12)
    assert _parse_int_pair("6") == (6, None)
    assert _parse_int_pair(6) == (6, None)
    assert _parse_int_pair([(6, 12)]) == (6, 12)
    assert _parse_int_pair(["6/12"]) == (6, 12)
    assert _parse_int_pair(None) == (None, None)
    assert _parse_int_pair("abc") == (None, None)


def test_parse_year_odd_formats():
    assert _parse_year("2024") == 2024
    assert _parse_year("2024-01-01") == 2024
    assert _parse_year(2024) == 2024
    assert _parse_year("circa 1999") == 1999
    assert _parse_year(None) is None
    assert _parse_year("unknown") is None


def test_detect_cover_art_various_tags():
    mock_audio = Mock()
    mock_audio.pictures = []
    mock_audio.tags = {}
    assert not _detect_cover_art(mock_audio)

    mock_audio.tags = {"covr": [b"data"]}
    assert _detect_cover_art(mock_audio)

    mock_audio.tags = {"metadata_block_picture": [b"data"]}
    assert _detect_cover_art(mock_audio)


def test_parse_first_string():
    assert _parse_first_string({"a": "val"}, "b", "a") == "val"
    assert _parse_first_string({"a": ["val"]}, "a") == "val"

    class MockText:
        def __init__(self, text):
            self.text = text

    assert _parse_first_string({"a": MockText(["val"])}, "a") == "val"


def test_extract_int_pair_from_tags():
    from vibeplay.scanner import _extract_int_pair_from_tags

    assert _extract_int_pair_from_tags({"TRCK": "6/12"}, "TRCK") == (6, 12)
    assert _extract_int_pair_from_tags({"TRCK": "6/12"}, "missing", "TRCK") == (6, 12)
    assert _extract_int_pair_from_tags(None, "TRCK") == (None, None)


def test_serialize_tags():
    from vibeplay.scanner import _serialize_tags

    assert _serialize_tags(None) == "{}"

    class MockText:
        def __init__(self, text):
            self.text = text

    tags = {"text_tag": MockText(["value"]), "list_tag": ["val1", "val2"], "bytes_tag": b"binary data", "int_tag": 123}

    import json

    result = json.loads(_serialize_tags(tags))
    assert result["text_tag"] == ["value"]
    assert result["list_tag"] == ["val1", "val2"]
    assert result["bytes_tag"] == "<binary data: 11 bytes>"
    assert result["int_tag"] == "123"


def test_extract_audio_properties():
    from vibeplay.scanner import _extract_audio_properties

    mock_audio = Mock()
    mock_audio.info = Mock()
    mock_audio.info.length = 120.5
    mock_audio.info.bitrate = 320000

    assert _extract_audio_properties(mock_audio) == (120.5, 320000)

    mock_audio.info = None
    assert _extract_audio_properties(mock_audio) == (None, None)
