"""The handful of engine levers for "the graphics memory is not enough".

llama.cpp has well over a hundred switches. Almost all of them are for
somebody building an engine, not for somebody running a model, and putting
them on a page would bury the five that actually change whether a model fits
on a machine. These five are those, and nothing else goes in here without a
reason a user could state.

Each one is passed only when it differs from what the engine already does.
An explicit flag that repeats the default is a flag that can go wrong later,
when the default moves and the program keeps insisting on the old one.

The names are read off the shipped binary, not remembered: `--mlock` is
deprecated in the build we ship and `--load-mode mlock` is what replaced it.
"""

from __future__ import annotations

from dataclasses import dataclass

# What the KV cache may be stored as. Just the engine's own default and the
# one quantized step worth taking: q8_0 halves the cache at essentially no
# quality loss once flash attention is on, which it always is now (auto).
# bf16/f32 buy nothing, and q4_0 loses more than the halving is worth — so
# there is no third step to choose between, only a switch.
KV_TYPEN = ("f16", "q8_0")
KV_VORGABE = "f16"

# Flash attention has no control in the window any more — the engine's
# "auto" decides. Keeping only "auto" valid means a stored "on"/"off" from
# an older version is clamped away by aus_daten instead of riding along
# forever with no switch left to change it.
FA_WERTE = ("auto",)
FA_VORGABE = "auto"

# The cache step an older version offered and this one does not: whoever
# stored it was saving memory on purpose, so it maps to the surviving
# saving step, not to the biggest cache.
KV_ALT = {"q4_0": "q8_0"}

# A thread count nobody would type on purpose. Above this the engine is being
# asked to fight itself for cores.
MAX_FAEDEN = 256

# Server slots (`--parallel`). The engine itself names no ceiling — it takes
# 64 and more without complaint — but every slot gets an equal share of the
# context window, so past this the shares stop being contexts. Measured on
# the shipped build: unset, the server picks its own count ("auto").
MAX_PARALLEL = 64


@dataclass
class Feineinstellungen:
    """What the advanced section can set. Every field defaults to "leave it"."""

    kv_cache: str = KV_VORGABE
    flash_attention: str = FA_VORGABE
    # None means: let the engine decide, which is what it does best.
    faeden: int | None = None
    # How many layers' worth of Mixture-of-Experts weights stay on the CPU.
    # 0 means none; None means all of them. THE lever for a MoE model on a
    # card that cannot hold it.
    moe_auf_cpu: bool = False
    moe_schichten: int | None = None
    # Keep the model in RAM instead of letting the system swap it out.
    festnageln: bool = False
    # How many requests the server serves at once (`--parallel`). None means
    # the engine's own "auto" — exactly what every start did before this
    # lever existed. The context is split evenly across the slots, which is
    # why this is a choice and not simply "more".
    parallel: int | None = None
    # Whether the slots share ONE cache of the window's size (`--kv-unified`)
    # or each gets the window divided by their number (`--no-kv-unified`).
    # Only said on the command line together with a slot count: with the
    # engine's own "auto" count it switches itself on.
    kv_unified: bool = True

    @classmethod
    def aus_daten(cls, daten: dict | None) -> "Feineinstellungen":
        """Builds from whatever the window sent, clamped into range.

        A value out of range is not an error to report but a value to bring
        into range — the same rule the picture generator follows. The one
        exception is a name that is not a name: an unknown cache type falls
        back to the default rather than reaching the command line, where the
        engine would refuse to start at all.
        """
        d = daten or {}
        kv = str(d.get("kv_cache") or KV_VORGABE)
        kv = KV_ALT.get(kv, kv)
        fa = str(d.get("flash_attention") or FA_VORGABE)
        faeden = d.get("faeden")
        try:
            faeden = None if faeden in (None, "", 0) else max(1, min(MAX_FAEDEN, int(faeden)))
        except (TypeError, ValueError):
            faeden = None
        schichten = d.get("moe_schichten")
        try:
            schichten = None if schichten in (None, "") else max(0, int(schichten))
        except (TypeError, ValueError):
            schichten = None
        parallel = d.get("parallel")
        try:
            parallel = (
                None
                if parallel in (None, "", 0)
                else max(1, min(MAX_PARALLEL, int(parallel)))
            )
        except (TypeError, ValueError):
            parallel = None
        # Missing is the shipped answer (on); only a stored false turns it off.
        unified = d.get("kv_unified")
        return cls(
            kv_cache=kv if kv in KV_TYPEN else KV_VORGABE,
            flash_attention=fa if fa in FA_WERTE else FA_VORGABE,
            faeden=faeden,
            moe_auf_cpu=bool(d.get("moe_auf_cpu")),
            moe_schichten=schichten,
            festnageln=bool(d.get("festnageln")),
            parallel=parallel,
            kv_unified=True if unified is None else bool(unified),
        )

    def als_daten(self) -> dict:
        return {
            "kv_cache": self.kv_cache,
            "flash_attention": self.flash_attention,
            "faeden": self.faeden,
            "moe_auf_cpu": self.moe_auf_cpu,
            "moe_schichten": self.moe_schichten,
            "festnageln": self.festnageln,
            "parallel": self.parallel,
            "kv_unified": self.kv_unified,
        }


def flags(einstellungen: Feineinstellungen | None) -> list[str]:
    """The command-line words for these settings, defaults left unsaid."""
    if einstellungen is None:
        return []
    zeile: list[str] = []

    # Both halves of the cache together: storing K small and V large saves
    # half of what was asked for and confuses anybody reading the command.
    if einstellungen.kv_cache != KV_VORGABE:
        zeile += ["--cache-type-k", einstellungen.kv_cache,
                  "--cache-type-v", einstellungen.kv_cache]

    if einstellungen.flash_attention != FA_VORGABE:
        zeile += ["--flash-attn", einstellungen.flash_attention]

    if einstellungen.faeden:
        zeile += ["--threads", str(einstellungen.faeden)]

    if einstellungen.moe_auf_cpu:
        # A number means "the first N layers", no number means all of them.
        if einstellungen.moe_schichten:
            zeile += ["--n-cpu-moe", str(einstellungen.moe_schichten)]
        else:
            zeile += ["--cpu-moe"]

    if einstellungen.festnageln:
        # `--mlock` still works but is deprecated in the shipped build; this
        # is the form that build documents.
        zeile += ["--load-mode", "mmap+mlock"]

    # Unset stays unsaid: the engine then picks its own slot count ("auto"),
    # which is what every start before this lever did.
    if einstellungen.parallel:
        zeile += [
            "--parallel", str(einstellungen.parallel),
            "--kv-unified" if einstellungen.kv_unified else "--no-kv-unified",
        ]

    return zeile


def context_per_request(context: int, einstellungen: Feineinstellungen | None) -> int | None:
    """The context one request gets, where it is not the whole window: with
    a slot count and the cache not shared, the window is divided by the
    slots. None where every request may use all of it."""
    if einstellungen is None or not einstellungen.parallel or einstellungen.parallel < 2:
        return None
    if einstellungen.kv_unified:
        return None
    return context // einstellungen.parallel
