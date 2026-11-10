from vibeplay.api.library import extract_cover_bytes


def test_non_existent_file_returns_none(tmp_path):
    assert extract_cover_bytes(tmp_path / "non_existent.flac") is None


def test_zero_byte_file_returns_none(tmp_path):
    mock_file = tmp_path / "zero_byte.flac"
    mock_file.touch()
    assert extract_cover_bytes(mock_file) is None


def test_folder_image_returned(tmp_path):
    mock_audio = tmp_path / "song.flac"
    mock_audio.touch()
    mock_cover = tmp_path / "cover.jpg"
    mock_cover.write_bytes(b"dummy_jpeg_data")

    result = extract_cover_bytes(mock_audio)
    assert result is not None
    assert result[0] == b"dummy_jpeg_data"
    assert result[1] == "image/jpeg"
