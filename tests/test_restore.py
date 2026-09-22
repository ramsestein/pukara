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


def test_perturbaciones_strict_recuperan_entidades():
    anon = _make_anon()
    anonymized = anon.anonymize(SAMPLE)
    text_to_ph = anon.text_to_ph
    assert text_to_ph  # debe haber detectado entidades
    for name in ("uppercase", "bold_markers", "space_inner", "label_translated",
                 "plural_suffix", "genitive_suffix", "split_by_newline"):
        restored = anon.deanonymize(utility.PERTURBATIONS[name](anonymized))
        assert all(orig in restored for orig in text_to_ph), name
    # strict NO recupera los que pierden corchetes (fallos honestos)
    for name in ("lost_brackets", "single_bracket"):
        restored = anon.deanonymize(utility.PERTURBATIONS[name](anonymized))
        assert not all(orig in restored for orig in text_to_ph), name


def test_no_restaura_placeholder_ausente():
    anon = _make_anon()
    anon.ph_to_text = {"[NOMBRE_1]": "María"}
    out = anon.deanonymize("El [NOMBRE_99] y [FECHA_7] quedan intactos.")
    assert "[NOMBRE_99]" in out
    assert "[FECHA_7]" in out


def test_variantes_restauracion_strict():
    anon = _make_anon()
    anon.ph_to_text = {"[NOMBRE_1]": "María"}
    assert anon.deanonymize("**[NOMBRE_1]**") == "María"
    assert anon.deanonymize("[NOMBRE_1]") == "María"
    assert anon.deanonymize("[ NOMBRE _ 1 ]") == "María"
    assert anon.deanonymize("[NOMBRE_1]s") == "María"
    assert anon.deanonymize("[NOMBRE_1]'s") == "María"
    assert anon.deanonymize("[NOMBRE_\n1]") == "María"
    assert anon.deanonymize("[NAME_1]") == "María"
    # mayúsculas
    assert anon.deanonymize("[nombre_1]") == "María"
    # strict NO recupera sin corchetes ni con un solo corchete
    assert anon.deanonymize("NOMBRE_1") == "NOMBRE_1"
    assert anon.deanonymize("[NOMBRE_1") == "[NOMBRE_1"
    assert anon.deanonymize("NOMBRE_1]") == "NOMBRE_1]"


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


def test_roundtrip_placeholders_literales():
    """Round-trip exacto cuando el texto ya contiene placeholders literales.

    Un placeholder generado (p. ej. [NOMBRE_1]) no debe confundirse con un
    literal igual, anidado o mal formado presente en la entrada.
    """
    anon = _make_anon()
    for x in [
        "Paciente: María García [NOMBRE_1] literal.",
        "Paciente: María García [[NOMBRE_1]] y [NOMBRE_2].",
        "Paciente: María García [NOMBRE_1",
        "Paciente: María García NOMBRE_1] y **[NOMBRE_1]**.",
        "Paciente: María García [ NOMBRE _ 1 ] y [NOMBRE_1]s.",
    ]:
        out = anon.anonymize(x)
        assert anon.deanonymize(out) == x, x


@settings(max_examples=200)
@given(st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"),
                           whitelist_characters=" []_*"),
    max_size=80,
))
def test_roundtrip_placeholders_literales_propiedad(base):
    """Propiedad: round-trip exacto con placeholders literales, anidados y
    mal formados generados por Hypothesis."""
    anon = _make_anon()
    x = base + " Paciente: María García López, tel 600123456."
    out = anon.anonymize(x)
    assert anon.deanonymize(out) == x


@settings(max_examples=200)
@given(st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"),
                           whitelist_characters=" .,;:()_"),
    max_size=80,
))
def test_strict_no_alterar_texto_sin_corchetes(base):
    """Propiedad: en `strict` ningún texto sin corchetes se altera."""
    anon = _make_anon()
    anon.ph_to_text = {"[NOMBRE_1]": "María", "[FECHA_1]": "12/05/2024"}
    assert anon.deanonymize(base) == base


@settings(max_examples=200)
@given(st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"),
                           whitelist_characters=" _"),
    max_size=60,
))
def test_no_restaurar_token_del_original(base):
    """Propiedad: un token tipo etiqueta presente en el prompt
    original nunca se restaura (salvaguarda del original). Se usan formas sin
    corchetes (`nombre_1`); las formas con corchetes literales las cubre el
    escape del round-trip."""
    anon = _make_anon()
    anon.ph_to_text = {"[NOMBRE_1]": "María", "[FECHA_2]": "12/05/2024",
                       "[ID_1]": "12345678Z"}
    anon.original_tokens = {t.lower() for t in base.split()}
    assert anon.deanonymize(base) == base
