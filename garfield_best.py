"""Compatibility adapter for the packaged Garfield assistant core."""

from garfield.conversation import assistant as _impl

globals().update({name: value for name, value in vars(_impl).items() if not name.startswith("__")})

__all__ = [name for name in vars(_impl) if not name.startswith("_")]


if __name__ == "__main__":
    raise SystemExit(_impl.main())
