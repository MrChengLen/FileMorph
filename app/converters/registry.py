from app.converters.base import BaseConverter, UnsupportedConversionError

# Maps (src_format, tgt_format) → converter class
_registry: dict[tuple[str, str], type[BaseConverter]] = {}

# Maps src_format → list of supported target formats
_supported: dict[str, list[str]] = {}


def register(*pairs: tuple[str, str]):
    """Class decorator: register a converter for one or more (src, tgt) pairs.

    Usage:
        @register(("heic", "jpg"), ("heif", "jpg"))
        class HeicToJpgConverter(BaseConverter): ...
    """

    def decorator(cls: type[BaseConverter]) -> type[BaseConverter]:
        for src, tgt in pairs:
            src, tgt = src.lower(), tgt.lower()
            _registry[(src, tgt)] = cls
            _supported.setdefault(src, [])
            if tgt not in _supported[src]:
                _supported[src].append(tgt)
        return cls

    return decorator


def get_converter(src_fmt: str, tgt_fmt: str) -> BaseConverter:
    """Return an instantiated converter for the given format pair."""
    key = (src_fmt.lower(), tgt_fmt.lower())
    if key not in _registry:
        raise UnsupportedConversionError(src_fmt, tgt_fmt)
    return _registry[key]()


def get_supported_conversions() -> dict[str, list[str]]:
    """Return a copy of the supported conversions map."""
    # Trigger lazy imports so all converters register themselves
    _ensure_loaded()
    return {src: list(tgts) for src, tgts in _supported.items()}


_loaded = False


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    # Import all converter modules to trigger @register decorators
    import app.converters.audio  # noqa: F401
    import app.converters.document  # noqa: F401
    import app.converters.image  # noqa: F401
    import app.converters.spreadsheet  # noqa: F401
    import app.converters.video  # noqa: F401
