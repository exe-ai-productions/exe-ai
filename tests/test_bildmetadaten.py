"""The strip step must leave a picture with pixels and nothing else."""

from __future__ import annotations

import struct
import zlib

from app.bildmetadaten import metadaten_entfernen

_PNG_SIGNATUR = b"\x89PNG\r\n\x1a\n"


def _png_block(typ: bytes, koerper: bytes) -> bytes:
    """One PNG chunk with a correct length and CRC, as a real file has."""
    pruef = zlib.crc32(typ + koerper) & 0xFFFFFFFF
    return struct.pack(">I", len(koerper)) + typ + koerper + struct.pack(">I", pruef)


def _jpeg_marker(marker: int, koerper: bytes) -> bytes:
    """One JPEG marker segment with its length, as a real file has."""
    return bytes([0xFF, marker]) + struct.pack(">H", len(koerper) + 2) + koerper


def _png_mit_metadaten() -> tuple[bytes, bytes]:
    """A tiny PNG that carries every kind of text/EXIF/time chunk."""
    ihdr = _png_block(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = _png_block(b"IDAT", zlib.compress(b"\x00\x11\x22\x33"))
    iend = _png_block(b"IEND", b"")
    metadaten = (
        _png_block(b"tEXt", b"parameters\x00GEHEIM-prompt-und-seed")
        + _png_block(b"zTXt", b"note\x00\x00" + zlib.compress(b"GEHEIM-komprimiert"))
        + _png_block(b"iTXt", b"XML\x00\x00\x00\x00\x00GEHEIM-xmp")
        + _png_block(b"eXIf", b"GEHEIM-exif-block")
        + _png_block(b"tIME", struct.pack(">HBBBBB", 2026, 8, 20, 11, 34, 0))
    )
    png = _PNG_SIGNATUR + ihdr + metadaten + idat + iend
    return png, idat


def test_png_verliert_jede_metadate_und_behaelt_die_pixel():
    png, idat = _png_mit_metadaten()
    sauber = metadaten_entfernen(png)

    for typ in (b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME"):
        assert typ not in sauber
    assert b"GEHEIM" not in sauber

    # The picture itself is byte-for-byte the same.
    assert sauber.startswith(_PNG_SIGNATUR)
    assert b"IHDR" in sauber
    assert idat in sauber
    assert sauber.endswith(_png_block(b"IEND", b""))


def test_png_putzen_ist_wiederholbar():
    png, _ = _png_mit_metadaten()
    einmal = metadaten_entfernen(png)
    # A file that is already clean must come back untouched.
    assert metadaten_entfernen(einmal) == einmal


def test_jpeg_verliert_exif_und_kommentar_behaelt_farbe_und_pixel():
    soi = b"\xff\xd8"
    app1 = _jpeg_marker(0xE1, b"Exif\x00\x00GEHEIM-gps")
    app0 = _jpeg_marker(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    kommentar = _jpeg_marker(0xFE, b"GEHEIM-kommentar")
    scan = b"\xff\xda" + struct.pack(">H", 3) + b"\x00" + b"PIXELDATEN"
    eoi = b"\xff\xd9"
    jpg = soi + app1 + app0 + kommentar + scan + eoi

    sauber = metadaten_entfernen(jpg)

    assert b"Exif" not in sauber
    assert b"GEHEIM" not in sauber
    assert b"JFIF" in sauber  # the colour/JFIF header stays for a true picture
    assert sauber.startswith(b"\xff\xd8") and sauber.endswith(b"\xff\xd9")
    assert b"PIXELDATEN" in sauber
    assert metadaten_entfernen(sauber) == sauber


def test_fremdes_format_bleibt_unangetastet():
    fremd = b"this is not an image at all"
    assert metadaten_entfernen(fremd) == fremd


def test_abgeschnittenes_png_wird_nicht_kaputtgemacht():
    png, _ = _png_mit_metadaten()
    stumpf = png[:-4]  # cut into the final chunk
    # A broken input is handed back as it came, never turned into garbage.
    assert metadaten_entfernen(stumpf) == stumpf


def _webp_chunk(kind: bytes, body: bytes) -> bytes:
    """One RIFF chunk, its body padded to an even length as a real file has."""
    return kind + struct.pack("<I", len(body)) + body + (b"\x00" if len(body) & 1 else b"")


def _webp(*chunks: bytes) -> bytes:
    body = b"WEBP" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


# The extended header: flags, three reserved bytes, width and height minus one.
_WEBP_PIXELS = _webp_chunk(b"VP8L", b"\x2f\x00\x00\x00\x00\x07\xd0\xff\xfe\xf7\xbf\xff\x81\x88\xe8\x7f\x00")
_WEBP_PROFILE = _webp_chunk(b"ICCP", b"colour-profile")


def _webp_header(flags: int) -> bytes:
    return _webp_chunk(b"VP8X", bytes([flags, 0, 0, 0, 0, 0, 0, 0, 0, 0]))


def test_a_webp_loses_exif_and_xmp_and_keeps_its_picture():
    """A WebP with an EXIF and an XMP chunk comes back without both: the
    pixel data and the colour profile are the same bytes, the header no
    longer announces what is gone, and the size in front is right."""
    picture = _webp(
        _webp_header(0x20 | 0x08 | 0x04), _WEBP_PROFILE, _WEBP_PIXELS,
        _webp_chunk(b"EXIF", b"SECRET-camera-and-place"),
        _webp_chunk(b"XMP ", b"<x:xmpmeta>SECRET-prompt</x:xmpmeta>"),
        _webp_chunk(b"abcd", b"SECRET-of-an-unnamed-chunk"),
    )
    clean = metadaten_entfernen(picture)
    assert clean == _webp(_webp_header(0x20), _WEBP_PROFILE, _WEBP_PIXELS)
    assert b"SECRET" not in clean
    assert struct.unpack("<I", clean[4:8])[0] == len(clean) - 8
    assert metadaten_entfernen(clean) == clean


def test_a_webp_without_metadata_stays_byte_for_byte():
    """Silence: nothing to remove, nothing changed — the plain file with
    only its pixels, the extended one, and one that is cut short."""
    plain = _webp(_WEBP_PIXELS)
    extended = _webp(_webp_header(0x20), _WEBP_PROFILE, _WEBP_PIXELS)
    assert metadaten_entfernen(plain) == plain
    assert metadaten_entfernen(extended) == extended
    carrying = _webp(_webp_header(0x08), _WEBP_PIXELS, _webp_chunk(b"EXIF", b"SECRET"))
    assert metadaten_entfernen(carrying[:-3]) == carrying[:-3]
    assert metadaten_entfernen(b"RIFF\x04\x00\x00\x00WAVE") == b"RIFF\x04\x00\x00\x00WAVE"

