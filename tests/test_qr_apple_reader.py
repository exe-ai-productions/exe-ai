"""The code of the web app is read by Apple's reader — the one the iPhone camera uses.

The page draws the code without a quiet zone of its own and lets it run to 3 px
of the edge of its light tile (132 px of code, 3 px of edge, a radius of 8 on
the tile). Chrome's reader and the Vision framework of macOS
(`VNDetectBarcodesRequest`) both have to read exactly that, for a short and a
long address, at the size of the page and far smaller and blurred. The tile is
drawn here from the modules of the real code (`app/qr_code.py` asks `segno` for
the same ones) with the page's measures, light on a dark card as on the page.

Runs where macOS and its Swift compiler are; skipped elsewhere.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app import qr_code

segno = pytest.importorskip("segno")
Image = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")
ImageFilter = pytest.importorskip("PIL.ImageFilter")

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("swiftc") is None,
    reason="the Vision framework needs macOS and its Swift compiler",
)

READER = """import Foundation
import Vision
import AppKit
let image = NSImage(contentsOfFile: CommandLine.arguments[1])!
let cg = NSBitmapImageRep(data: image.tiffRepresentation!)!.cgImage!
let request = VNDetectBarcodesRequest()
request.symbologies = [.qr]
try VNImageRequestHandler(cgImage: cg, options: [:]).perform([request])
let found = (request.results ?? []).compactMap { $0.payloadStringValue }
print(found.isEmpty ? "NONE" : found.joined(separator: " | "))
"""

ADDRESSES = [
    "https://m.tailnet-name.ts.net/app",
    "https://exe-mac-studio-upstairs-office.tailnet-name.ts.net:8443/app",
]


@pytest.fixture(scope="module")
def reader(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("vision")
    (folder / "read_qr.swift").write_text(READER, encoding="utf-8")
    built = subprocess.run(
        ["swiftc", "-O", str(folder / "read_qr.swift"), "-o", str(folder / "read_qr")],
        capture_output=True, text=True, timeout=240,
    )
    assert built.returncode == 0, built.stderr[-1500:]
    return folder / "read_qr"


def _tile(address: str, size: int) -> Any:
    """The tile as the page draws it: the code of `qr_code`'s modules, 3/132 of
    its width of light edge, the tile rounded by 8/138, all on a dark card with
    16/138 around it."""
    matrix = segno.make(address, error="m").matrix
    modules = len(matrix)
    unit = size / 138
    side = round(138 * unit)
    margin = round(16 * unit)
    image = Image.new("RGB", (side + 2 * margin, side + 2 * margin), (42, 42, 40))
    tile = Image.new("RGB", (side, side), (244, 243, 238))
    code = ImageDraw.Draw(tile)
    edge = 3 * unit
    step = 132 * unit / modules
    for row, line in enumerate(matrix):
        for column, dark in enumerate(line):
            if dark:
                code.rectangle(
                    [edge + column * step, edge + row * step, edge + (column + 1) * step - 1, edge + (row + 1) * step - 1],
                    fill=(0, 0, 0),
                )
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, side - 1, side - 1], radius=8 * unit, fill=255)
    image.paste(tile, (margin, margin), mask)
    return image


def _read(reader: Path, image: Any, folder: Path) -> str:
    path = folder / "tile.png"
    image.save(path)
    return subprocess.run([str(reader), str(path)], capture_output=True, text=True, timeout=60).stdout.strip()


@pytest.mark.parametrize("address", ADDRESSES)
@pytest.mark.parametrize("size", [138, 276, 414])
def test_the_tile_with_its_3_px_edge_is_read_at_the_size_of_the_page(reader, tmp_path, address, size):
    assert _read(reader, _tile(address, size), tmp_path) == address


@pytest.mark.parametrize("address", ADDRESSES)
def test_it_is_still_read_far_smaller_and_blurred(reader, tmp_path, address):
    small = _tile(address, 414)
    small = small.resize((round(small.width * 0.3), round(small.height * 0.3)), Image.LANCZOS)
    assert _read(reader, small.filter(ImageFilter.GaussianBlur(1.0)), tmp_path) == address


def test_the_drawing_has_no_border_of_its_own_and_the_modules_are_the_ones_of_the_real_code():
    address = ADDRESSES[1]
    modules = len(segno.make(address, error="m").matrix)
    assert f'viewBox="0 0 {modules} {modules}"' in qr_code.svg(address)
