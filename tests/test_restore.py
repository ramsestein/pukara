"""Tests de restauración tolerante de placeholders (Fase D).

Sin BERT: usan el detector regex-only (`_regex_detect`) para probar
round-trip y perturbaciones de forma rápida y determinista.
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from eval import utility
from src import anonymizer


def _make_anon():
    anon = anonymizer.Anonymizer.__new__(anonymizer.Anonymizer)
    anon.reset()
    anon.detect = anon._regex_detect
    return anon


SAMPLE = (
    "Paciente María García López, 45 años. Tel 600123456. "
    "Email maria.garcia@example.com. NHC 1234567. Ciudad: Barcelona."
)


def test_roundtrip_exacto():
    anon = _make_anon()
    out = anon.anonymize(SAMPLE)
    assert anon.deanonymize(out) == SAMPLE


def test_perturbaciones_recuperan_entidades():
    anon = _make_anon()
    anonymized = anon.anonymize(SAMPLE)
    text_to_ph = anon.text_to_ph
    assert text_to_ph  # debe haber detectado entidades
    for name, perturb in utility.PERTURBATIONS.items():
        restored = anon.deanonymize(perturb(anonymized))
        assert all(orig in restored for orig in text_to_ph), name


def test_no_restaura_placeholder_ausente():
    anon = _make_anon()
    anon.ph_to_text = {"[NOMBRE_1]": "María"}
    out = anon.deanonymize("El [NOMBRE_99] y [FECHA_7] quedan intactos.")
    assert "[NOMBRE_99]" in out
    assert "[FECHA_7]" in out


def test_variantes_restauracion():
    anon = _make_anon()
    anon.ph_to_text = {"[NOMBRE_1]": "María"}
    assert anon.deanonymize("**[NOMBRE_1]**") == "María"
    assert anon.deanonymize("[NOMBRE_1]") == "María"
    assert anon.deanonymize("NOMBRE_1") == "María"
    assert anon.deanonymize("[ NOMBRE _ 1 ]") == "María"
    assert anon.deanonymize("[NOMBRE_1]s") == "María"
    assert anon.deanonymize("[NOMBRE_1]'s") == "María"
    assert anon.deanonymize("[NOMBRE_\n1]") == "María"
    assert anon.deanonymize("[NAME_1]") == "María"
    # mayúsculas
    assert anon.deanonymize("[nombre_1]") == "María"


def test_no_rompe_numero_mayor():
    anon = _make_anon()
    anon.ph_to_text = {"[NOMBRE_1]": "María", "[NOMBRE_10]": "Luis"}
    out = anon.deanonymize("[NOMBRE_10] y [NOMBRE_1]")
    assert out == "Luis y María"


@settings(max_examples=150)
@given(st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"),
                           whitelist_characters=" .,;:()"),
    max_size=120,
))
def test_roundtrip_propiedad(base):
    anon = _make_anon()
    x = base + " Paciente: María García López, tel 600123456."
    out = anon.anonymize(x)
    assert anon.deanonymize(out) == x
