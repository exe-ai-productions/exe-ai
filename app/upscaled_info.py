"""What a picture that was enlarged says about the enlarging: by what factor
and how large it is now.

Both come out of the files. The size is the finished picture's own width and
height, not the original's times a factor, so it is true where the picture
server crops or rounds. The factor is the finished width over the original's
width, a whole number or else one decimal. Where the original cannot be read
(it is gone, or it is no picture) only the size stands; where the finished
picture cannot be read, nothing does.
"""

from __future__ import annotations

from pathlib import Path

from app import attachment_sizes


def of(original: Path | None, result: Path) -> dict | None:
    """``{"faktor": 4, "breite": 4096, "hoehe": 4096}``, the factor left out
    where the original is not readable, or ``None`` where the result is not."""
    done = attachment_sizes.of_file(result)
    if done is None:
        return None
    info: dict = {"breite": done["width"], "hoehe": done["height"]}
    before = attachment_sizes.of_file(original) if original is not None else None
    if before is not None:
        factor = round(done["width"] / before["width"], 1)
        info = {"faktor": int(factor) if factor == int(factor) else factor, **info}
    return info
