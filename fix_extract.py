with open("src/vibeplay/scanner.py", "r") as f:
    content = f.read()

new_content = content.replace(
    """    # Open file with mutagen in read mode
    audio = mutagen.File(file_path)
    if audio is None:
        raise ValueError(f"Mutagen could not recognize audio format: {file_path}")""",
    """    # Open file with mutagen in read mode
    try:
        audio = mutagen.File(file_path)
    except Exception as e:
        raise ValueError(f"Mutagen could not recognize audio format: {file_path}") from e

    if audio is None:
        raise ValueError(f"Mutagen could not recognize audio format: {file_path}")""",
)

with open("src/vibeplay/scanner.py", "w") as f:
    f.write(new_content)
