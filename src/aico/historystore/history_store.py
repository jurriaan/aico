from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import ClassVar

from .models import SHARD_SIZE, HistoryRecord, dumps_history_record, load_history_record


class HistoryStore:
    """
    Append-only, sharded JSONL store for HistoryRecord objects.

    - Uses global, zero-based indices as canonical pointers.
    - Physically shards files by SHARD_SIZE lines each: 0.jsonl, 10000.jsonl, ...
    - No meta.json; state is derived from the filesystem.
    """

    _SHARD_RE: ClassVar[re.Pattern[str]] = re.compile(r"^(\d+)\.jsonl$")

    root: Path
    shard_size: int
    _last_shard_base: int | None
    _last_shard_count: int

    def __init__(self, root: Path, shard_size: int = SHARD_SIZE) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.shard_size = shard_size
        self._last_shard_base = None
        self._last_shard_count = 0

    # ---------- Public API ----------

    def next_index(self) -> int:
        """
        Returns the next global index to be assigned.
        """
        base, count = self._resolve_last_shard_and_count()
        return (base or 0) + count

    def append(self, record: HistoryRecord) -> int:
        """
        Appends a single record as a JSON line, returns assigned global index.
        """
        base, count = self._resolve_last_shard_and_count()
        if base is None:
            base = 0
            count = 0

        # Start a new shard if the current is full
        if count >= self.shard_size:
            base += self.shard_size
            count = 0

        index = base + count
        shard_path = self._shard_path(base)
        self._append_line(shard_path, dumps_history_record(record))

        # Update cache
        self._last_shard_base = base
        self._last_shard_count = count + 1
        return index

    def append_pair(self, user: HistoryRecord, assistant: HistoryRecord) -> tuple[int, int]:
        """
        Appends two records (typically a user/assistant pair) back-to-back.
        """
        first_idx = self.append(user)
        second_idx = self.append(assistant)
        return first_idx, second_idx

    def read(self, index: int) -> HistoryRecord:
        """
        Reads a single record by global index.
        """
        shard_base = self._shard_base_for(index)
        local_offset = self._local_offset(index)
        shard_path = self._shard_path(shard_base)
        if not shard_path.is_file():
            raise IndexError(f"Record index {index} out of range (missing shard).")

        try:
            with shard_path.open("r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i == local_offset:
                        return load_history_record(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"Corrupt JSON in shard {shard_path}: {e}") from e

        raise IndexError(f"Record index {index} out of range (offset not found).")

    def read_many(self, indices: Sequence[int]) -> list[HistoryRecord]:
        """
        Reads multiple records efficiently by grouping indices per shard.

        Returns results in the same order as the input indices.
        """
        if not indices:
            return []

        grouped: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for pos, idx in enumerate(indices):
            shard_base = self._shard_base_for(idx)
            grouped[shard_base].append((pos, self._local_offset(idx)))

        results: list[HistoryRecord | None] = [None] * len(indices)

        for shard_base, positions in grouped.items():
            shard_path = self._shard_path(shard_base)
            if not shard_path.is_file():
                raise IndexError(f"Missing shard for indices in base {shard_base}")

            needed_offsets = {off for _, off in positions}
            offset_to_pos: dict[int, list[int]] = defaultdict(list)
            for pos, off in positions:
                offset_to_pos[off].append(pos)

            found: dict[int, HistoryRecord] = {}
            try:
                with shard_path.open("r", encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        if i in needed_offsets:
                            found[i] = load_history_record(line)
                            if len(found) == len(needed_offsets):
                                break
            except json.JSONDecodeError as e:
                raise ValueError(f"Corrupt JSON in shard {shard_path}: {e}") from e

            # Map found records back to their positions
            for off, rec in found.items():
                for pos in offset_to_pos[off]:
                    results[pos] = rec

        # Ensure none are missing
        if any(r is None for r in results):
            missing_positions = [i for i, r in enumerate(results) if r is None]
            raise IndexError(f"One or more indices were not found: positions {missing_positions}")

        return [rec for rec in results if rec is not None]

    # ---------- Helpers ----------

    def shard_path_for(self, index: int) -> Path:
        return self._shard_path(self._shard_base_for(index))

    def local_offset(self, index: int) -> int:
        return self._local_offset(index)

    # ---------- Internal ----------

    def _append_line(self, path: Path, line: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            _ = f.write(line)
            _ = f.write("\n")
            f.flush()
            with suppress(OSError):
                _ = os.fsync(f.fileno())

    def _resolve_last_shard_and_count(self) -> tuple[int | None, int]:
        """
        Determines the base offset of the last shard file and its current line count.

        Uses a simple per-instance cache to avoid recounting when appending consecutively.
        """
        shard_files = self._list_shard_files()
        if not shard_files:
            # No shards yet
            self._last_shard_base = None
            self._last_shard_count = 0
            return None, 0

        last_base, last_path = shard_files[-1]
        if self._last_shard_base == last_base and self._last_shard_count > 0:
            return last_base, self._last_shard_count

        count = self._count_lines(last_path)
        self._last_shard_base = last_base
        self._last_shard_count = count
        return last_base, count

    def _list_shard_files(self) -> list[tuple[int, Path]]:
        files: list[tuple[int, Path]] = []
        for entry in self.root.iterdir():
            if not entry.is_file():
                continue
            m = self._SHARD_RE.match(entry.name)
            if not m:
                continue
            base = int(m.group(1))
            files.append((base, entry))
        files.sort(key=lambda t: t[0])
        return files

    def _count_lines(self, path: Path) -> int:
        # Efficient line count bounded by shard size
        count = 0
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 64), b""):
                count += chunk.count(b"\n")
        return count

    def _shard_base_for(self, index: int) -> int:
        if index < 0:
            raise IndexError("Negative indices are not supported in HistoryStore.")
        return (index // self.shard_size) * self.shard_size

    def _local_offset(self, index: int) -> int:
        return index % self.shard_size

    def _shard_path(self, base: int) -> Path:
        return self.root / f"{base}.jsonl"
