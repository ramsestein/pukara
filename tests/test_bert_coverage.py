"""La detección BERT debe cubrir el texto completo (regresión 1.2.1).

En una ejecución de 2026-09, BERT solo procesó la primera ventana de 512
tokens de cada documento. `check_bert_coverage` debe fallar en ese caso.
"""
from pathlib import Path

import pytest

from src import anonymizer

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "models" / "bsc-bio-ehr-es-carmen-anon"
LONG_TEXT = " ".join(f"Paciente {i} acude a control en consulta externa." for i in range(200))


class _OneWindowTokenizer:
    """Simula el fallo: devuelve solo la primera ventana."""
    model_max_length = 512

    def __call__(self, text, **_kwargs):
        return {"offset_mapping": [[(0, 0), (0, 10), (10, 20), (0, 0)]]}


class _FullTokenizer(_OneWindowTokenizer):
    def __call__(self, text, **_kwargs):
        n = len(text)
        return {"offset_mapping": [[(0, 0), (0, n // 2), (0, 0)],
                                   [(0, 0), (n // 2, n), (0, 0)]]}


def _anon(tokenizer):
    anon = anonymizer.Anonymizer.__new__(anonymizer.Anonymizer)
    anon.reset()
    anon.tokenizer = tokenizer
    anon.detect = lambda text: []
    return anon


def test_una_sola_ventana_bloquea():
    anon = _anon(_OneWindowTokenizer())
    with pytest.raises(RuntimeError, match="BERT windows cover"):
        anon.check_bert_coverage(LONG_TEXT)
    with pytest.raises(RuntimeError):
        anon.anonymize(LONG_TEXT)


def test_cobertura_completa_no_bloquea():
    anon = _anon(_FullTokenizer())
    anon.check_bert_coverage(LONG_TEXT)
    assert anon.anonymize(LONG_TEXT) == LONG_TEXT


def test_sin_tokenizer_no_aplica():
    anon = anonymizer.Anonymizer.__new__(anonymizer.Anonymizer)
    anon.reset()
    anon.check_bert_coverage(LONG_TEXT)


@pytest.mark.skipif(not MODEL.exists(), reason="modelo BERT no disponible")
def test_tokenizer_real_genera_varias_ventanas():
    from transformers import AutoTokenizer

    anon = _anon(AutoTokenizer.from_pretrained(str(MODEL), local_files_only=True))
    enc = anon.tokenizer(LONG_TEXT, return_overflowing_tokens=True,
                         stride=anon.STRIDE, truncation=True,
                         max_length=anon.tokenizer.model_max_length,
                         return_offsets_mapping=True)
    assert len(enc["input_ids"]) > 1
    anon.check_bert_coverage(LONG_TEXT)
