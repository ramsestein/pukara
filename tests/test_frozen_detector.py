"""Test de congelación (fase 4): la detección no cambió respecto a
`eval-frozen-v2`.

Compara el hash de las funciones de detección y de los patrones regex del
`src/anonymizer.py` actual con los del tag `eval-frozen-v2`. Si un cambio futuro
toca la detección (regex, umbral, lista blanca, BERT, dedup), este test falla y
obliga a re-congelar explícitamente.

Los cambios de restauración/escape (`_restore_placeholder`, `_escape_*`,
`_unescape_*`, `anonymize`, `deanonymize`, `reset`) quedan fuera del hash.
"""
import ast
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "src" / "anonymizer.py"

# Funciones de detección y constantes regex que deben permanecer congeladas.
DETECTION_FUNCTIONS = [
    "_bert_detect",
    "_regex_detect",
    "detect",
    "_hospital_spans",
    "_map_bert_label",
    "_map_step2_label",
    "_valid_dni",
    "_valid_nie",
    "_load_whitelist",
]
DETECTION_CONSTANTS = ["PATTERNS", "IDENTIFIER_PATTERNS"]


def _hash_detection(source: str) -> str:
    tree = ast.parse(source)
    parts = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in DETECTION_FUNCTIONS:
                parts.append(ast.get_source_segment(source, node))
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in DETECTION_CONSTANTS:
                    parts.append(ast.get_source_segment(source, node))
    blob = "\n".join(p for p in parts if p)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _frozen_source() -> str:
    return subprocess.check_output(
        ["git", "show", "eval-frozen-v2:src/anonymizer.py"],
        cwd=ROOT,
    ).decode("utf-8")


def test_deteccion_congelada():
    current = FILE.read_text(encoding="utf-8")
    frozen = _frozen_source()
    assert _hash_detection(current) == _hash_detection(frozen), (
        "La detección de src/anonymizer.py difiere de eval-frozen-v2. "
        "No se toca la detección (regex/umbral/lista blanca/BERT/dedup); "
        "si el cambio es intencionado, re-congela explícitamente."
    )
