"""Microsoft Presidio como componente del detector de Pukara.

Presidio (spaCy `es_core_news_lg` + reconocedores por defecto) aporta a la
detección únicamente estas clases del conjunto unificado:

  - `PERSON`        -> `NAME`
  - `EMAIL_ADDRESS` -> `EMAIL`
  - `LOCATION`      -> `LOCATION` (países y ciudades; spaCy no distingue)

Carga perezosa: el motor NLP (~570 MB) solo se carga la primera vez que se
usa. Si Presidio o el modelo no están instalados, `available()` devuelve False
y las funciones devuelven listas vacías (el detector degrada a BERT+regex sin
romperse).

`detect_full` expone el baseline standalone: todas las entidades de Presidio
mapeadas al conjunto unificado (usado por la evaluación comparativa, Fase F2).
"""
from __future__ import annotations

# Mapeo completo de entidades de Presidio -> taxonomía unificada (baseline).
PRESIDIO_TO_UNIFIED = {
    "PERSON": "NAME",
    "LOCATION": "LOCATION",
    "ORG": "ORGANIZATION",
    "DATE_TIME": "DATE",
    "PHONE_NUMBER": "PHONE",
    "EMAIL_ADDRESS": "EMAIL",
    "URL": "URL",
    "IBAN_CODE": "ID",
    "CREDIT_CARD": "ID",
    "NRP": "ID",          # número de pasaporte
    "MEDICAL_LICENSE": "ID",
    "US_DRIVER_LICENSE": "ID",
    "UK_NHS": "ID",
    "AU_ABN": "ID",
    "AU_ACN": "ID",
    "AU_TFN": "ID",
    "AU_MEDICARE": "ID",
    "SG_NRIC_FIN": "ID",
}

# Solo estas clases contribuyen al detector integrado (BERT + regex + Presidio).
_LIMITED = {
    "PERSON": "NAME",
    "EMAIL_ADDRESS": "EMAIL",
    "LOCATION": "LOCATION",
}

_ANALYZER = None
_LOAD_FAILED = False


def _engine():
    global _ANALYZER, _LOAD_FAILED
    if _ANALYZER is None and not _LOAD_FAILED:
        try:
            from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
            from presidio_analyzer.nlp_engine import NlpEngineProvider

            config = {
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "es", "model_name": "es_core_news_lg"}],
            }
            provider = NlpEngineProvider(nlp_configuration=config)
            nlp_engine = provider.create_engine()
            registry = RecognizerRegistry()
            registry.load_predefined_recognizers(nlp_engine=nlp_engine, languages=["es"])
            _ANALYZER = AnalyzerEngine(nlp_engine=nlp_engine, registry=registry)
        except Exception as exc:  # noqa: BLE001
            _LOAD_FAILED = True
            print(f"[presidio] no disponible, degradando a BERT+regex: {exc}")
    return _ANALYZER


def available() -> bool:
    return _engine() is not None


def _analyze(text: str):
    eng = _engine()
    if eng is None:
        return []
    try:
        return eng.analyze(text=text, language="es")
    except Exception as exc:  # noqa: BLE001
        print(f"[presidio] error de análisis: {exc}")
        return []


def _to_entities(results, label_map) -> list[dict]:
    ents = []
    for r in results:
        lab = label_map.get(r.entity_type)
        if lab is None:
            continue
        if r.start >= r.end:
            continue
        ents.append({"start": r.start, "end": r.end, "label": lab,
                     "text": ""})
    # Rellenar el texto una sola vez (evita repetir el slice en cada entidad).
    return ents


def detect_limited(text: str) -> list[dict]:
    """Entidades NAME/EMAIL/LOCATION de Presidio para el detector integrado."""
    ents = []
    for r in _analyze(text):
        lab = _LIMITED.get(r.entity_type)
        if lab is None or r.start >= r.end:
            continue
        ents.append({"start": r.start, "end": r.end, "label": lab,
                     "text": text[r.start:r.end]})
    return ents


def detect_full(text: str) -> list[dict]:
    """Todas las entidades de Presidio mapeadas (baseline standalone)."""
    ents = []
    for r in _analyze(text):
        lab = PRESIDIO_TO_UNIFIED.get(r.entity_type)
        if lab is None or r.start >= r.end:
            continue
        ents.append({"start": r.start, "end": r.end, "label": lab,
                     "text": text[r.start:r.end]})
    # Dedup por solape: el span más largo gana (un email no deja que su dominio
    # aparezca además como URL).
    deduped = []
    for e in sorted(ents, key=lambda x: (x["start"], -(x["end"] - x["start"]))):
        if not any(e["start"] < k["end"] and k["start"] < e["end"] for k in deduped):
            deduped.append(e)
    deduped.sort(key=lambda x: x["start"])
    return deduped
