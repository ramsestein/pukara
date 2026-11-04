"""Regresiones de restauración corregidas en 1.2.1.

1. Peticiones con varios mensajes: los marcadores de escape deben ser únicos
   en toda la petición y el mapa no debe sobrescribirse ni vaciarse entre
   mensajes (texto ordinario como «Hospital 12» u «hora 14» se escapa).
2. Restauración en una sola pasada: el texto ya restaurado no se vuelve a
   interpretar (p. ej. la «s» de un original no es el sufijo plural de un
   placeholder posterior).
"""
from src import anonymizer, privacy


def _make_anon(detect=None):
    anon = anonymizer.Anonymizer.__new__(anonymizer.Anonymizer)
    anon.reset()
    anon.detect = detect or (lambda text: [])
    return anon


def test_escapes_unicos_entre_mensajes():
    anon = _make_anon()
    body = {"messages": [
        {"role": "user", "content": "Ingresó en el Hospital 12."},
        {"role": "assistant", "content": "Entendido."},
        {"role": "user", "content": "Control a la hora 14."},
    ]}
    privacy.anonymize_body(anon, body)
    first, last = body["messages"][0]["content"], body["messages"][2]["content"]
    m1 = first[len("Ingresó en el "):-1]
    m2 = last[len("Control a la "):-1]
    assert m1 != m2  # marcadores distintos
    echo = f"{m1} / {m2}"
    assert anon.deanonymize(echo) == "Hospital 12 / hora 14"


def test_mensaje_sin_escapes_no_vacia_el_mapa():
    anon = _make_anon()
    body = {"messages": [
        {"role": "user", "content": "Ingresó en el Hospital 12."},
        {"role": "user", "content": "Sin nada que escapar."},
    ]}
    privacy.anonymize_body(anon, body)
    marker = body["messages"][0]["content"][len("Ingresó en el "):-1]
    assert anon.deanonymize(marker) == "Hospital 12"


def test_reset_borra_el_mapa_de_escapes():
    anon = _make_anon()
    anon.anonymize("Hospital 12")
    assert anon.escapes
    anon.reset()
    assert anon.escapes == {}


def test_restauracion_una_pasada_no_consume_texto_restaurado():
    anon = _make_anon()
    anon.ph_to_text = {"[NOMBRE_1]": "Ana", "[LUGAR_1]": "san"}
    assert anon.deanonymize("[NOMBRE_1][LUGAR_1]") == "Anasan"
    anon.ph_to_text = {"[LUGAR_1]": "Ana", "[NOMBRE_1]": "san"}
    assert anon.deanonymize("[LUGAR_1][NOMBRE_1]") == "Anasan"


def test_restauracion_una_pasada_original_con_aspecto_de_placeholder():
    # Un original que contiene texto con forma de placeholder no se reinterpreta.
    anon = _make_anon()
    anon.ph_to_text = {"[NOMBRE_2]": "[NOMBRE_1]", "[NOMBRE_1]": "Ana"}
    assert anon.deanonymize("[NOMBRE_2] y [NOMBRE_1]") == "[NOMBRE_1] y Ana"


def test_roundtrip_entidades_pegadas():
    text = "Paciente Anasan ingresó."

    def detect(t):
        i = t.find("Anasan")
        if i < 0:
            return []
        return [{"start": i, "end": i + 3, "label": "NAME", "text": "Ana"},
                {"start": i + 3, "end": i + 6, "label": "LOCATION", "text": "san"}]

    anon = _make_anon(detect)
    out = anon.anonymize(text)
    assert out == "Paciente [NOMBRE_1][LUGAR_1] ingresó."
    assert anon.deanonymize(out) == text
