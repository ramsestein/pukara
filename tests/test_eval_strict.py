"""Métricas complementarias del evaluador (v1.2.1)."""
from eval import common
from src import anonymizer


def test_strict_coverage_estados():
    text = "Ana Pérez, tel 600123456."
    gold = [{"start": 0, "end": 9, "label": "NAME"},
            {"start": 15, "end": 24, "label": "PHONE"},
            {"start": 11, "end": 14, "label": "OTHER"}]
    rows = common.strict_coverage(text, gold, [(0, 3), (15, 24)])
    assert [r["status"] for r in rows] == ["partial", "full", "missed"]
    assert rows[0]["alnum_residual"] is True
    # Un resto de solo espacio/puntuación no es residuo alfanumérico.
    rows = common.strict_coverage("Ana Pérez.", [{"start": 0, "end": 10, "label": "NAME"}],
                                  [(0, 9)])
    assert rows[0]["status"] == "partial" and rows[0]["alnum_residual"] is False


def test_anonymize_with_removed_offsets_originales_con_escape():
    anon = anonymizer.Anonymizer.__new__(anonymizer.Anonymizer)
    anon.reset()
    anon.detect = anon._regex_detect
    text = "Ver [NOMBRE_1] y llamar al 600123456."
    out, removed, _preds, escaped = common.anonymize_with_removed(anon, text)
    assert escaped != text
    phone = text.index("600123456")
    assert (phone, phone + 9) in removed
    assert (4, 14) in removed  # el literal escapado también se retira
    assert anon.deanonymize(out) == text
    assert anon.detect == anon._regex_detect
