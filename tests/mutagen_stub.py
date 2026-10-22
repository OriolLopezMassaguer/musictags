"""Lets `import core` work where mutagen is not installed (CI, sandboxes). The tests that use it
only exercise the pure tag-proposal logic, never file I/O. With mutagen installed it does nothing."""
import sys
import types


def install():
    try:
        import mutagen  # noqa: F401
        return
    except ImportError:
        pass
    mod = types.ModuleType("mutagen")
    mod.File = lambda *a, **k: None
    id3 = types.ModuleType("mutagen.id3")
    id3.ID3 = type("ID3", (), {})
    id3.ID3NoHeaderError = type("ID3NoHeaderError", (Exception,), {})
    id3.Frames = {}
    id3.TXXX = type("TXXX", (), {})
    mp4 = types.ModuleType("mutagen.mp4")
    mp4.MP4 = type("MP4", (), {})
    mp4.MP4FreeForm = type("MP4FreeForm", (bytes,), {})
    mod.id3, mod.mp4 = id3, mp4
    sys.modules.update({"mutagen": mod, "mutagen.id3": id3, "mutagen.mp4": mp4})


install()
