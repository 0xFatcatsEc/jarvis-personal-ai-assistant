"""Readable UTF-8 project exports with all-or-nothing file publication."""
import json
import os
import tempfile
from pathlib import Path

from ..contracts.messages import Code, Failure
from ..settings import local_data_path


def write_manifest(target: Path, manifest: dict[str, object]) -> Path:
    if (not target.is_absolute() or target.suffix.lower() != ".json"
            or any(":" in part or Path(part).is_reserved() for part in target.parts[1:])):
        raise Failure(Code.INPUT)
    # Resolve the directory only. An existing file or link at the chosen name
    # must fail publication, even if the link's target does not exist.
    directory = local_data_path(target.parent)
    destination = directory / target.name
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "nt":
            temporary.rename(destination)  # Windows rename refuses an existing destination.
            temporary = None
        else:
            os.link(temporary, destination)
        return destination
    except FileExistsError as exc:
        raise Failure(Code.CONFLICT, field="export_filename") from exc
    except OSError as exc:
        raise Failure(Code.STORE, field="export_destination") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
