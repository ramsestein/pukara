"""Test obligatorio (fase 2): el punto estimado está dentro de su propio IC.

Para cada JSON de `eval/results/` y cada métrica con `ci95`, comprueba que
`ci95[0] <= punto <= ci95[1]`. Los IC deben ser coherentes con el estimador:
cociente agregado con bootstrap de cociente, medias por documento con bootstrap
de media.
"""
import json
from pathlib import Path

import pytest

RESULTS = Path(__file__).resolve().parent.parent / "eval" / "results"
JSON_FILES = sorted(p.name for p in RESULTS.glob("*.json") if not p.name.startswith("."))

_CI_POINT = (
    ("f1_ci95", "f1"),
    ("ci95", "rate"),
    ("rate_ci95", "rate"),
    ("char_rate_ci95", "char_rate"),
)


def _walk(obj, path=""):
    if isinstance(obj, dict):
        for ci_key, point_key in _CI_POINT:
            if ci_key in obj and point_key in obj:
                lo, hi = obj[ci_key]
                yield path, point_key, obj[point_key], lo, hi
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")


@pytest.mark.parametrize("name", JSON_FILES)
def test_punto_dentro_del_ic(name):
    data = json.loads((RESULTS / name).read_text(encoding="utf-8"))
    problemas = []
    for path, point_key, p, lo, hi in _walk(data, name):
        if p is None:
            continue
        if not (lo <= p <= hi):
            problemas.append(f"{path}: {point_key}={p} fuera de CI [{lo}, {hi}]")
    assert not problemas, "\n".join(problemas)
