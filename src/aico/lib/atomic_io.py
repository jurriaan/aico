import os
from pathlib import Path
from tempfile import mkstemp


def atomic_write_text(path: Path, text: str | bytes, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = mkstemp(suffix=path.suffix, prefix=path.name + ".tmp", dir=path.parent)
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            match text:
                case str():
                    _ = f.write(text)
                case bytes():
                    _ = f.write(text.decode(encoding))

        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)
