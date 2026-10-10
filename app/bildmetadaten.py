"""Stripping a picture down to its pixels before it is stored.

A generator writes more than an image into its file: the image tool puts the
full prompt, the seed, the model name and every setting into a PNG text
field, and an uploaded photo can carry EXIF — camera, timestamp, place. None
of that is the picture, and all of it would travel to a cloud model the
moment one is switched on. So the bytes are cleaned in one place, on the way
to disk, and only what a viewer needs to draw the image survives.

The pixels are never touched: chunks and markers are copied through verbatim
or dropped whole. There is no re-encoding, so there is no quality or colour
change — a cleaned picture is the same picture with nothing written beside it.

An unknown or broken file is handed back unchanged. Refusing to guess is the
safe answer: better an untouched file than a corrupted one.
"""

from __future__ import annotations

import struct

_PNG_SIGNATUR = b"\x89PNG\r\n\x1a\n"

# PNG chunk types that carry text, EXIF or a timestamp — everything a person
# would not want to hand out. Every other chunk is pixel or rendering data
# (palette, transparency, colour profile, gamma) and is kept as it was.
_PNG_WEG = {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME"}

# JPEG application markers worth keeping: JFIF header (0xE0), ICC colour
# profile (0xE2), Adobe colour-transform flag (0xEE). Every other APPn marker
# holds metadata (EXIF, XMP, IPTC, Photoshop) and is dropped, as is the
# comment marker.
_JPEG_BEHALTEN = {0xE0, 0xE2, 0xEE}


def _png_saeubern(daten: bytes) -> bytes:
    """A PNG with every text/EXIF/time chunk removed, pixels untouched."""
    heraus = bytearray(_PNG_SIGNATUR)
    stelle = len(_PNG_SIGNATUR)
    laenge = len(daten)
    fertig = False
    while stelle + 8 <= laenge:
        (blocklaenge,) = struct.unpack(">I", daten[stelle:stelle + 4])
        typ = daten[stelle + 4:stelle + 8]
        # A chunk is length(4) + type(4) + body + crc(4).
        ende = stelle + 12 + blocklaenge
        if ende > laenge:
            return daten  # truncated — leave the input alone
        if typ not in _PNG_WEG:
            heraus += daten[stelle:ende]
        stelle = ende
        if typ == b"IEND":
            # Anything past the end marker (some tools append data there) is
            # left behind on purpose.
            fertig = True
            break
    if not fertig:
        return daten  # no end marker — do not hand back a half file
    return bytes(heraus)


def _jpeg_saeubern(daten: bytes) -> bytes:
    """A JPEG with every metadata and comment marker removed."""
    heraus = bytearray(daten[:2])  # start of image
    stelle = 2
    laenge = len(daten)
    while stelle + 1 < laenge:
        if daten[stelle] != 0xFF:
            return daten  # not where a marker should be — do not touch it
        marker = daten[stelle + 1]
        # A run of 0xFF is allowed as padding between markers.
        if marker == 0xFF:
            heraus.append(0xFF)
            stelle += 1
            continue
        # Start of scan: the compressed pixels run to the end. Copy the rest
        # verbatim and stop — no metadata lives past this point.
        if marker == 0xDA:
            heraus += daten[stelle:]
            return bytes(heraus)
        # Markers that carry no length: start/end of image, restart, TEM.
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            heraus += daten[stelle:stelle + 2]
            stelle += 2
            continue
        if stelle + 4 > laenge:
            return daten
        (segmentlaenge,) = struct.unpack(">H", daten[stelle + 2:stelle + 4])
        ende = stelle + 2 + segmentlaenge
        if ende > laenge:
            return daten
        weg = marker == 0xFE or (0xE0 <= marker <= 0xEF and marker not in _JPEG_BEHALTEN)
        if not weg:
            heraus += daten[stelle:ende]
        stelle = ende
    return bytes(heraus)


# WebP chunks a viewer draws the picture from: the header of the extended
# format, the colour profile, the animation and its frames, the alpha plane
# and the two kinds of pixel data. Every other chunk — EXIF, XMP, and any
# chunk the format does not name — is dropped.
_WEBP_KEPT = {b"VP8X", b"ICCP", b"ANIM", b"ANMF", b"ALPH", b"VP8 ", b"VP8L"}
# The two bits of the extended header that announce an EXIF and an XMP chunk.
_WEBP_METADATA_FLAGS = 0x08 | 0x04


def _webp_clean(data: bytes) -> bytes:
    """A WebP with its EXIF and XMP chunks removed, pixels untouched. The
    container is a RIFF file: a size, the word WEBP, then chunks of a
    four-letter kind, a length and a body padded to an even length."""
    if len(data) < 12:
        return data
    (size,) = struct.unpack("<I", data[4:8])
    end = 8 + size
    if end > len(data):
        return data  # truncated — leave the input alone
    kept = bytearray()
    dropped = False
    place = 12
    while place + 8 <= end:
        kind = data[place:place + 4]
        (length,) = struct.unpack("<I", data[place + 4:place + 8])
        stop = place + 8 + length + (length & 1)
        if stop > end:
            return data
        if kind not in _WEBP_KEPT:
            dropped = True
        elif kind == b"VP8X" and length >= 1:
            header = bytearray(data[place:stop])
            header[8] &= 0xFF ^ _WEBP_METADATA_FLAGS
            kept += header
        else:
            kept += data[place:stop]
        place = stop
    if place != end or not dropped:
        # Not laid out as chunks to the end, or nothing to remove: the file
        # stays byte for byte what it was.
        return data
    return b"RIFF" + struct.pack("<I", 4 + len(kept)) + b"WEBP" + bytes(kept)


def metadaten_entfernen(daten: bytes) -> bytes:
    """Return the image bytes with all text, EXIF and timestamp data removed.

    The format is read from the bytes themselves, not from a name, so a
    mislabelled file is still handled correctly. A format that is not a PNG,
    a JPEG or a WebP is handed back unchanged.
    """
    if daten.startswith(_PNG_SIGNATUR):
        return _png_saeubern(daten)
    if daten.startswith(b"\xff\xd8"):
        return _jpeg_saeubern(daten)
    if daten.startswith(b"RIFF") and daten[8:12] == b"WEBP":
        return _webp_clean(daten)
    return daten
