from pathlib import Path

def get_ext(file_path: str) -> str:
    return Path(file_path).suffix.lower()
