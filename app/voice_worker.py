"""The voice, kept loaded, in a process of its own.

``llama-tts`` loads the voice model, its projector and the voice sample for
every sentence and ends. A conversation speaks many pieces in a row, and
two seconds of loading per piece is most of the wait. This program loads
them once and speaks one piece after the other, with the same library
``llama-tts`` is built on (``libmtmd``, the audio generation helper) and the
same steps: the prompt, then one audio frame per step until the end of
speech, then the waveform.

It runs as a separate process on purpose. The library is an early interface
that changes between builds, and a build it was not written against fails
by stopping the process it runs in. Here that is this child alone: the
service sees the pipe close and goes on speaking through ``llama-tts``.

Protocol: one JSON object per line on standard input, one per line on the
private reply channel. The library and the engine print to the usual
output, so that is pointed at standard error and the replies travel on a
copy of the original descriptor made first. A finished piece is written to
the file the request names; its bytes never travel on the pipe.

    {"op": "load", "library_dir", "model", "mmproj", "speaker", "gpu_layers", "threads"}
    {"op": "speak", "text", "language", "sampling", "out"}
    {"op": "quit"}
"""

from __future__ import annotations

import array
import ctypes
import json
import os
import struct
import sys
import time
import wave
from ctypes import POINTER, byref, c_bool, c_char_p, c_float, c_int32, c_int64, c_size_t, c_uint32, c_void_p
from pathlib import Path
from typing import Any

# The llama.cpp build this was written against. The libraries it loads are a
# copy of exactly this build (app/voice_library.py).
LAYOUT_BUILD = "b11429"

# The sizes and offsets of the library's parameter blocks for that build.
# Every one is checked against the defaults the library itself returns before
# anything is changed (see ``_check_layout``): a build whose blocks look
# different is refused, not written into.
MODEL_PARAMS_SIZE = 80
CONTEXT_PARAMS_SIZE = 160
MTMD_PARAMS_SIZE = 88
OFFSET_GPU_LAYERS = 0x10
OFFSET_CTX = 0x00
OFFSET_BATCH = 0x04
OFFSET_UBATCH = 0x08
OFFSET_SEQ_MAX = 0x0C
OFFSET_THREADS = 0x1C
OFFSET_THREADS_BATCH = 0x20
OFFSET_FLAGS = 0x80  # embeddings, offload_kqv, no_perf, op_offload, swa_full, kv_unified

# The context both ways of speaking run with — this process and `llama-tts`
# (app/stimme.py) read the same number. Without a context of its own the
# engine takes the model's (32768), puts 3.5 GB of attention cache on the
# graphics card and, on a machine with 8 GB, refuses every sentence.
VOICE_CONTEXT_SIZE = 4096
# The C interface has no "auto" for the layer count: a negative number is how
# it says "all of them". A voice with no count named loads with this.
ALL_LAYERS = -1
BATCH_SIZE = 512
# The longest piece, in audio frames (twelve and a half per second): a
# safety stop, not a limit on what is said.
MAX_FRAMES = 3000
# What the engine's own sampler chain starts from when nothing is set.
PENALTY_WINDOW = 64
RANDOM_SEED = 0xFFFFFFFF
# What `llama-tts` of the same build takes for a value it is not given (read
# from its own `--help`, llama.cpp b11429). A value left out of a request is
# "Auto", and Auto is these.
AUTO_SAMPLING = {
    "temperature": 0.8,
    "top_k": 40,
    "top_p": 0.95,
    "min_p": 0.05,
    "repeat_penalty": 1.05,
}
OUT_TYPE_WAV = 1


class WorkerError(Exception):
    """A request this process cannot serve; the text goes back to the service."""


def library_names() -> tuple[str, str]:
    """The files of the engine's core library and of its audio library."""
    if sys.platform == "win32":
        return "llama.dll", "mtmd.dll"
    if sys.platform == "darwin":
        return "libllama.dylib", "libmtmd.dylib"
    return "libllama.so", "libmtmd.so"


def _blob(size: int) -> type:
    """A block of bytes the size of one of the library's parameter structs.

    Made a little larger than measured, never smaller: the library returns
    these by value, and what it does not write stays as it was."""
    return type(f"Blob{size}", (ctypes.Structure,), {"_fields_": [("raw", ctypes.c_ubyte * size)]})


class GenerationInput(ctypes.Structure):
    """``mtmd_helper_gen_audio_inp``."""

    _fields_ = [
        ("seq_id", c_int32),
        ("prompt", c_char_p),
        ("prompt_len", c_size_t),
        ("speaker_ref", c_void_p),
        ("lang", c_char_p),
        ("top_k", c_int32),
        ("top_p", c_float),
        ("seed", c_uint32),
        ("out_type", c_int32),
    ]


class ChainParams(ctypes.Structure):
    """``llama_sampler_chain_params``."""

    _fields_ = [("no_perf", c_bool)]


WAVE_FORMAT_EXTENSIBLE = 0xFFFE
WAVE_FORMAT_PCM = 1


def _read_extensible(path: str) -> tuple[int, int, int, bytes]:
    """A WAV whose format tag is WAVE_FORMAT_EXTENSIBLE (65534) with PCM
    audio inside — what macOS's `afconvert` writes. Python's `wave` knows
    that tag only from 3.12; the service runs on 3.11, so the two chunks
    that matter are read here: the format block (channels, rate, width and
    the sub-format's own tag) and the data. Returns (channels, width, rate,
    raw); anything that is not PCM inside is refused like any other format."""
    data = Path(path).read_bytes()
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise WorkerError("speaker_format")
    position, fmt, audio = 12, None, None
    while position + 8 <= len(data):
        name = data[position:position + 4]
        size = struct.unpack_from("<I", data, position + 4)[0]
        body = data[position + 8:position + 8 + size]
        if name == b"fmt ":
            fmt = body
        elif name == b"data":
            audio = body
            break
        position += 8 + size + (size & 1)
    if fmt is None or audio is None or len(fmt) < 26:
        raise WorkerError("speaker_format")
    tag, channels, source_rate, _bytes_rate, _align, bits = struct.unpack_from("<HHIIHH", fmt, 0)
    # The block after the 16 classic bytes: its size, the valid bits, the
    # channel mask, and the sub-format's GUID — whose first two bytes are
    # the classic tag.
    subtag = struct.unpack_from("<H", fmt, 24)[0]
    if tag != WAVE_FORMAT_EXTENSIBLE or subtag != WAVE_FORMAT_PCM or channels < 1:
        raise WorkerError("speaker_format")
    return channels, bits // 8, source_rate, audio


def read_speaker(path: str, rate: int) -> list[float]:
    """The voice sample as mono floats at the rate the model reads.

    Plain 16-bit PCM, and the same inside a WAVE_FORMAT_EXTENSIBLE header
    (the way macOS writes it): anything else is refused here and the service
    speaks through ``llama-tts`` instead."""
    try:
        with wave.open(path, "rb") as source:
            channels, width, source_rate = source.getnchannels(), source.getsampwidth(), source.getframerate()
            raw = source.readframes(source.getnframes())
    except wave.Error as failure:
        # `wave` refuses the tag it does not know before it reads a byte.
        if f"unknown format: {WAVE_FORMAT_EXTENSIBLE}" not in str(failure):
            raise WorkerError("speaker_format") from failure
        channels, width, source_rate, raw = _read_extensible(path)
    if width != 2:
        raise WorkerError("speaker_format")
    ints = array.array("h")
    ints.frombytes(raw)
    if sys.byteorder == "big":
        ints.byteswap()
    mono = [sum(ints[i:i + channels]) / channels / 32768.0 for i in range(0, len(ints) - channels + 1, channels)]
    if not mono:
        raise WorkerError("speaker_empty")
    if source_rate == rate:
        return mono
    count = max(1, int(len(mono) * rate / source_rate))
    step = source_rate / rate
    out = []
    last = len(mono) - 1
    for index in range(count):
        position = index * step
        low = min(int(position), last)
        high = min(low + 1, last)
        fraction = position - low
        out.append(mono[low] * (1.0 - fraction) + mono[high] * fraction)
    return out


class Voice:
    """The loaded voice: model, context, projector, generation helper."""

    def __init__(self) -> None:
        self.llama: Any = None
        self.mtmd: Any = None
        self.model = None
        self.context = None
        self.mtmd_context = None
        self.generation = None
        self.bitmap = None
        self.rate = 0

    # --- loading ---------------------------------------------------------

    def _bind(self, library_dir: str) -> None:
        directory = Path(library_dir)
        if sys.platform == "win32":
            os.add_dll_directory(str(directory))  # type: ignore[attr-defined]
        core, audio = library_names()
        try:
            self.llama = ctypes.CDLL(str(directory / core))
            self.mtmd = ctypes.CDLL(str(directory / audio))
        except OSError as error:
            raise WorkerError(f"library: {error}") from None
        llama, mtmd = self.llama, self.mtmd
        try:
            self._model_params = _blob(MODEL_PARAMS_SIZE + 32)
            self._context_params = _blob(CONTEXT_PARAMS_SIZE + 32)
            self._mtmd_params = _blob(MTMD_PARAMS_SIZE + 32)
            llama.llama_model_default_params.restype = self._model_params
            llama.llama_context_default_params.restype = self._context_params
            mtmd.mtmd_context_params_default.restype = self._mtmd_params
            llama.llama_model_load_from_file.argtypes = [c_char_p, self._model_params]
            llama.llama_model_load_from_file.restype = c_void_p
            llama.llama_init_from_model.argtypes = [c_void_p, self._context_params]
            llama.llama_init_from_model.restype = c_void_p
            mtmd.mtmd_init_from_file.argtypes = [c_char_p, c_void_p, self._mtmd_params]
            mtmd.mtmd_init_from_file.restype = c_void_p
            mtmd.mtmd_support_audio.argtypes = [c_void_p]
            mtmd.mtmd_support_audio.restype = c_bool
            mtmd.mtmd_get_audio_sample_rate.argtypes = [c_void_p]
            mtmd.mtmd_get_audio_sample_rate.restype = c_int32
            mtmd.mtmd_bitmap_init_from_audio.argtypes = [c_size_t, POINTER(c_float)]
            mtmd.mtmd_bitmap_init_from_audio.restype = c_void_p
            mtmd.mtmd_bitmap_free.argtypes = [c_void_p]
            mtmd.mtmd_free.argtypes = [c_void_p]
            mtmd.mtmd_helper_gen_audio_init.argtypes = [c_void_p, c_void_p]
            mtmd.mtmd_helper_gen_audio_init.restype = c_void_p
            mtmd.mtmd_helper_gen_audio_free.argtypes = [c_void_p]
            mtmd.mtmd_helper_gen_audio_reset.argtypes = [c_void_p]
            mtmd.mtmd_helper_gen_audio_set_input.argtypes = [c_void_p, POINTER(GenerationInput)]
            mtmd.mtmd_helper_gen_audio_set_input.restype = c_int32
            mtmd.mtmd_helper_gen_audio_step_prompt.argtypes = [c_void_p, c_int32]
            mtmd.mtmd_helper_gen_audio_step_prompt.restype = c_int32
            mtmd.mtmd_helper_gen_audio_step_gen.argtypes = [
                c_void_p, c_int32, POINTER(c_float), POINTER(POINTER(c_float)), POINTER(c_bool),
            ]
            mtmd.mtmd_helper_gen_audio_step_gen.restype = c_int32
            mtmd.mtmd_helper_gen_audio_get_output.argtypes = [
                c_void_p, POINTER(c_int32), POINTER(c_char_p), POINTER(c_size_t), POINTER(c_int64),
            ]
            mtmd.mtmd_helper_gen_audio_get_output.restype = c_int32
            llama.llama_backend_init.argtypes = []
            llama.llama_free.argtypes = [c_void_p]
            llama.llama_model_free.argtypes = [c_void_p]
            llama.llama_get_memory.argtypes = [c_void_p]
            llama.llama_get_memory.restype = c_void_p
            llama.llama_memory_clear.argtypes = [c_void_p, c_bool]
            llama.llama_get_embeddings_ith.argtypes = [c_void_p, c_int32]
            llama.llama_get_embeddings_ith.restype = POINTER(c_float)
            llama.llama_sampler_chain_default_params.restype = ChainParams
            llama.llama_sampler_chain_init.argtypes = [ChainParams]
            llama.llama_sampler_chain_init.restype = c_void_p
            llama.llama_sampler_chain_add.argtypes = [c_void_p, c_void_p]
            llama.llama_sampler_free.argtypes = [c_void_p]
            llama.llama_sampler_sample.argtypes = [c_void_p, c_void_p, c_int32]
            llama.llama_sampler_sample.restype = c_int32
            llama.llama_sampler_init_penalties.argtypes = [c_int32, c_float, c_float, c_float]
            llama.llama_sampler_init_penalties.restype = c_void_p
            llama.llama_sampler_init_top_k.argtypes = [c_int32]
            llama.llama_sampler_init_top_k.restype = c_void_p
            llama.llama_sampler_init_top_p.argtypes = [c_float, c_size_t]
            llama.llama_sampler_init_top_p.restype = c_void_p
            llama.llama_sampler_init_min_p.argtypes = [c_float, c_size_t]
            llama.llama_sampler_init_min_p.restype = c_void_p
            llama.llama_sampler_init_temp.argtypes = [c_float]
            llama.llama_sampler_init_temp.restype = c_void_p
            llama.llama_sampler_init_dist.argtypes = [c_uint32]
            llama.llama_sampler_init_dist.restype = c_void_p
        except AttributeError as error:
            # A build without the audio generation helper.
            raise WorkerError(f"library_missing_function: {error}") from None

    def _check_layout(self, context_params: Any, model_params: Any) -> None:
        """The defaults the library hands back must look like the blocks this
        file knows. Anything else is another build."""
        raw = bytes(context_params.raw)
        ctx, batch, ubatch, seq_max = struct.unpack_from("<4i", raw, 0)
        flags = raw[OFFSET_FLAGS:OFFSET_FLAGS + 6]
        known = (
            (ctx, batch, ubatch, seq_max) == (512, 2048, 512, 1)
            and flags == bytes([0, 1, 1, 1, 1, 0])
        )
        if not known:
            raise WorkerError("layout_unknown")
        model_raw = bytes(model_params.raw)
        # The model block holds the GPU layer count at its known offset, a
        # small signed number in every build seen.
        value = struct.unpack_from("<i", model_raw, OFFSET_GPU_LAYERS)[0]
        if not -1 <= value <= 1000:
            raise WorkerError("layout_unknown")

    def load(self, request: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        self._bind(str(request["library_dir"]))
        llama, mtmd = self.llama, self.mtmd
        llama.llama_backend_init()
        model_params = llama.llama_model_default_params()
        context_params = llama.llama_context_default_params()
        self._check_layout(context_params, model_params)

        struct.pack_into("<i", model_params, OFFSET_GPU_LAYERS, int(request.get("gpu_layers", 99)))
        self.model = llama.llama_model_load_from_file(str(request["model"]).encode(), model_params)
        if not self.model:
            raise WorkerError("model_not_loaded")

        threads = int(request.get("threads") or 0) or min(8, os.cpu_count() or 4)
        struct.pack_into("<i", context_params, OFFSET_CTX, VOICE_CONTEXT_SIZE)
        struct.pack_into("<i", context_params, OFFSET_BATCH, BATCH_SIZE)
        struct.pack_into("<i", context_params, OFFSET_UBATCH, BATCH_SIZE)
        struct.pack_into("<i", context_params, OFFSET_THREADS, threads)
        struct.pack_into("<i", context_params, OFFSET_THREADS_BATCH, threads)
        struct.pack_into("<B", context_params, OFFSET_FLAGS, 1)  # embeddings: the hidden states are read
        self.context = llama.llama_init_from_model(self.model, context_params)
        if not self.context:
            raise WorkerError("context_not_created")

        self.mtmd_context = mtmd.mtmd_init_from_file(
            str(request["mmproj"]).encode(), self.model, mtmd.mtmd_context_params_default()
        )
        if not self.mtmd_context or not mtmd.mtmd_support_audio(self.mtmd_context):
            raise WorkerError("projector_not_loaded")
        self.rate = int(mtmd.mtmd_get_audio_sample_rate(self.mtmd_context))

        speaker = request.get("speaker")
        if speaker:
            samples = read_speaker(str(speaker), self.rate)
            data = (c_float * len(samples))(*samples)
            self.bitmap = mtmd.mtmd_bitmap_init_from_audio(len(samples), data)
            if not self.bitmap:
                raise WorkerError("speaker_not_read")

        self.generation = mtmd.mtmd_helper_gen_audio_init(self.context, self.mtmd_context)
        if not self.generation:
            raise WorkerError("generation_not_created")
        return {"ok": True, "rate": self.rate, "seconds": round(time.monotonic() - started, 2)}

    # --- speaking --------------------------------------------------------

    def _sampler_chain(self, sampling: dict[str, Any]) -> Any:
        llama = self.llama
        chain = llama.llama_sampler_chain_init(llama.llama_sampler_chain_default_params())
        penalty = float(sampling.get("repeat_penalty", AUTO_SAMPLING["repeat_penalty"]))
        for stage in (
            llama.llama_sampler_init_penalties(PENALTY_WINDOW, penalty, 0.0, 0.0),
            llama.llama_sampler_init_top_k(int(sampling.get("top_k", AUTO_SAMPLING["top_k"]))),
            llama.llama_sampler_init_top_p(float(sampling.get("top_p", AUTO_SAMPLING["top_p"])), 1),
            llama.llama_sampler_init_min_p(float(sampling.get("min_p", AUTO_SAMPLING["min_p"])), 1),
            llama.llama_sampler_init_temp(float(sampling.get("temperature", AUTO_SAMPLING["temperature"]))),
            llama.llama_sampler_init_dist(RANDOM_SEED),
        ):
            llama.llama_sampler_chain_add(chain, stage)
        return chain

    def speak(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.generation is None:
            raise WorkerError("not_loaded")
        llama, mtmd = self.llama, self.mtmd
        started = time.monotonic()
        sampling = dict(request.get("sampling") or {})
        text = str(request["text"]).encode("utf-8")
        language = str(request.get("language") or "").encode() or None

        # Each piece starts from an empty memory: the previous one's
        # positions are still in it, and a prompt on top of them is refused.
        llama.llama_memory_clear(llama.llama_get_memory(self.context), True)
        mtmd.mtmd_helper_gen_audio_reset(self.generation)
        inp = GenerationInput(
            0, text, len(text), self.bitmap, language,
            int(sampling.get("top_k", AUTO_SAMPLING["top_k"])),
            float(sampling.get("top_p", AUTO_SAMPLING["top_p"])),
            RANDOM_SEED, OUT_TYPE_WAV,
        )
        if mtmd.mtmd_helper_gen_audio_set_input(self.generation, byref(inp)) != 0:
            raise WorkerError("input_refused")
        while True:
            step = mtmd.mtmd_helper_gen_audio_step_prompt(self.generation, BATCH_SIZE)
            if step == 0:
                break
            if step < 0:
                raise WorkerError("prompt_failed")

        chain = self._sampler_chain(sampling)
        try:
            hidden = llama.llama_get_embeddings_ith(self.context, -1)
            stop = c_bool(False)
            frames = 0
            while not stop.value and frames < MAX_FRAMES:
                token = llama.llama_sampler_sample(chain, self.context, -1)
                following = POINTER(c_float)()
                if mtmd.mtmd_helper_gen_audio_step_gen(
                    self.generation, token, hidden, byref(following), byref(stop)
                ) != 0:
                    raise WorkerError("frame_failed")
                if not following:
                    break
                hidden = following
                frames += 1
        finally:
            llama.llama_sampler_free(chain)

        rate, data, length, samples = c_int32(), c_char_p(), c_size_t(), c_int64()
        if mtmd.mtmd_helper_gen_audio_get_output(
            self.generation, byref(rate), byref(data), byref(length), byref(samples)
        ) != 0 or not length.value:
            raise WorkerError("no_output")
        Path(str(request["out"])).write_bytes(ctypes.string_at(data, length.value))
        return {
            "ok": True,
            "frames": frames,
            "samples": int(samples.value),
            "rate": int(rate.value),
            "seconds": round(time.monotonic() - started, 2),
        }

    # --- ending ----------------------------------------------------------

    def close(self) -> None:
        """Gives everything back in the order it was taken."""
        llama, mtmd = self.llama, self.mtmd
        if llama is None:
            return
        if self.generation:
            mtmd.mtmd_helper_gen_audio_free(self.generation)
        if self.bitmap:
            mtmd.mtmd_bitmap_free(self.bitmap)
        if self.mtmd_context:
            mtmd.mtmd_free(self.mtmd_context)
        if self.context:
            llama.llama_free(self.context)
        if self.model:
            llama.llama_model_free(self.model)
        self.generation = self.bitmap = self.mtmd_context = self.context = self.model = None


def main() -> int:
    # The reply channel is a copy of the original descriptor; what the
    # engine prints goes to standard error from here on.
    reply = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)
    voice = Voice()

    def answer(payload: dict[str, Any]) -> None:
        reply.write(json.dumps(payload) + "\n")
        reply.flush()

    for line in sys.stdin:
        try:
            request = json.loads(line)
        except ValueError:
            continue
        operation = request.get("op") if isinstance(request, dict) else None
        if operation == "quit":
            break
        try:
            if operation == "load":
                answer(voice.load(request))
            elif operation == "speak":
                answer(voice.speak(request))
            else:
                answer({"ok": False, "error": "unknown_operation"})
        except WorkerError as error:
            answer({"ok": False, "error": str(error)})
        except Exception as error:  # noqa: BLE001 - whatever it was, the service falls back
            answer({"ok": False, "error": f"{type(error).__name__}: {error}"})
    try:
        voice.close()
    finally:
        reply.flush()
    # Ended here, not by the interpreter: the engine's own shutdown hooks
    # run into freed devices otherwise.
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
