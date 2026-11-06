from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Iterable, Sequence

# Prefijos que Excel/LibreOffice interpretan como fórmula (CSV injection).
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _clean(value, sanitize: bool):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if sanitize and isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def write_csv(path: Path, rows: Iterable[dict], fieldnames: Sequence[str], sanitize: bool = True) -> int:
    """Escritura atómica, UTF-8 con BOM (Power BI/Excel detectan el encoding)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _clean(row.get(k), sanitize) for k in fieldnames})
            count += 1
    os.replace(tmp, path)
    return count


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
