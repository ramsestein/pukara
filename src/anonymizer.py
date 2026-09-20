"""Self-contained anonymization layer (BERT + regex).

Detects entities with:
  - BERT `bsc-bio-ehr-es-carmen-anon` (multiclass token classification).
  - Regex rules (dates, times, phones, names, addresses, etc.).

and replaces them with reversible placeholders `[TAG_n]`. The
`placeholder -> real text` map lives only on the client; the server receives
only placeholders, subject to the detector's recall (missed entities are
transmitted in the clear — see docs/threat-model.md).

No dependencies on `carmina_3_suite/`: all the relevant code lives here.
The only external resource is the BERT model, stored under `models/`.
"""
import hashlib
import os
import re
from pathlib import Path

from . import PROJECT_ROOT

ROOT = PROJECT_ROOT
DEFAULT_MODEL_REPO = "BSC-NLP4BIA/bsc-bio-ehr-es-carmen-anon"
DEFAULT_MODEL_DIR = Path(os.environ.get("CARMINA_MODEL_DIR", ROOT / "models"))


def _read_env(key, default=""):
    if os.environ.get(key):
        return os.environ[key]
    try:
        with open(ROOT / ".env", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return default


def model_repo():
    return _read_env("BERT_MODEL", DEFAULT_MODEL_REPO)


def model_dirname():
    return model_repo().split("/")[-1]


def verify_model_hash(model_path):
    """Verify the BERT weights file against BERT_MODEL_SHA256 (if set).

    Returns True when no hash is configured or no weights file is found.
    """
    expected = _read_env("BERT_MODEL_SHA256").strip().lower()
    if not expected:
        return True
    model_path = Path(model_path)
    for name in ("model.safetensors", "pytorch_model.bin"):
        f = model_path / name
        if f.exists():
            sha = hashlib.sha256()
            with open(f, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    sha.update(chunk)
            return sha.hexdigest() == expected
    return True  # no weights file to verify

# ── Unified taxonomy ────────────────────────────────────────────────────────
# BRAT (CARMEN) -> unified taxonomy
BRAT_TO_UNIFIED = {
    "FECHAS": "DATE",
    "HORAS": "TIME",
    # The CARMEN model has no NOMBRE_SUJETO_ASISTENCIA class: it emits patient
    # names as NOMBRE_PERSONAL_SANITARIO. Both person-name classes are merged
    # into NAME because anonymization treats any person name identically.
    "NOMBRE_SUJETO_ASISTENCIA": "NAME",
    "NOMBRE_PERSONAL_SANITARIO": "NAME",
    "FAMILIARES_SUJETO_ASISTENCIA": "FAMILY",
    "PROFESION": "PROFESSION",
    "EDAD_SUJETO_ASISTENCIA": "AGE",
    "SEXO_SUJETO_ASISTENCIA": "SEX",
    "CALLE": "LOCATION",
    "TERRITORIO": "LOCATION",
    "PAIS": "LOCATION",
    "HOSPITAL": "HOSPITAL",
    "CENTRO_SALUD": "HOSPITAL",
    "INSTITUCION": "ORGANIZATION",
    "NUMERO_TELEFONO": "PHONE",
    "NUMERO_FAX": "PHONE",
    "CORREO_ELECTRONICO": "EMAIL",
    "URL_WEB": "URL",
    "NUMERO_IDENTIF": "ID",
    "ID_SUJETO_ASISTENCIA": "ID",
    "ID_CONTACTO_ASISTENCIAL": "ID",
    "ID_ASEGURAMIENTO": "ID",
    "ID_EMPLEO_PERSONAL_SANITARIO": "ID",
    "ID_TITULACION_PERSONAL_SANITARIO": "ID",
    "OTROS_SUJETO_ASISTENCIA": "OTHER",
}

# step2 (regex) labels -> unified taxonomy
STEP2_TO_UNIFIED = {
    "DATE": "DATE",
    "TIME": "TIME",
    "PHONE": "PHONE",
    # "Dr./Dra. X" is a person name for anonymization purposes.
    "DOCTOR": "NAME",
    "AGE": "AGE",
    "LOCATION": "LOCATION",
    "RELATION": "FAMILY",
    "IDENTIFICADOR": "ID",
    "HOSPITAL": "HOSPITAL",
    "PERSON": "NAME",
    "EMAIL": "EMAIL",
    "URL": "URL",
    "GENERICA": "OTHER",
}

# Unified label -> readable tag for the placeholder
TAGS = {
    "DATE": "FECHA",
    "TIME": "HORA",
    "NAME": "NOMBRE",
    "PROFESSIONAL": "PROFESIONAL",
    "FAMILY": "FAMILIAR",
    "PROFESSION": "PROFESION",
    "AGE": "EDAD",
    "SEX": "SEXO",
    "LOCATION": "LUGAR",
    "HOSPITAL": "HOSPITAL",
    "ORGANIZATION": "ORGANIZACION",
    "PHONE": "TELEFONO",
    "EMAIL": "CORREO",
    "URL": "URL",
    "ID": "ID",
    "OTHER": "ANONIMO",
    "PHI": "ANONIMO",
}

# Traducción de etiquetas de placeholder para la restauración tolerante:
# [NOMBRE_1] se reconoce también como [NAME_1], etc.
_TAG_ALIASES = {
    "NOMBRE": ("NOMBRE", "NAME"),
    "FECHA": ("FECHA", "DATE"),
    "HORA": ("HORA", "TIME"),
    "PROFESIONAL": ("PROFESIONAL", "PROFESSIONAL"),
    "FAMILIAR": ("FAMILIAR", "FAMILY"),
    "PROFESION": ("PROFESION", "PROFESSION"),
    "EDAD": ("EDAD", "AGE"),
    "SEXO": ("SEXO", "SEX"),
    "LUGAR": ("LUGAR", "LOCATION"),
    "HOSPITAL": ("HOSPITAL",),
    "ORGANIZACION": ("ORGANIZACION", "ORGANIZATION"),
    "TELEFONO": ("TELEFONO", "PHONE"),
    "CORREO": ("CORREO", "EMAIL"),
    "URL": ("URL",),
    "ID": ("ID",),
    "ANONIMO": ("ANONIMO", "ANONYMOUS", "OTHER"),
}


def _ph_parts(ph: str) -> tuple:
    """Extrae (tag, número) de un placeholder `[TAG_n]`."""
    inner = ph.strip("[]")
    if "_" in inner:
        tag, num = inner.rsplit("_", 1)
    else:
        tag, num = inner, ""
    return tag, num


def _ph_num(ph: str) -> int:
    num = _ph_parts(ph)[1]
    return int(num) if num.isdigit() else 0


def _restore_placeholder(text: str, ph: str, orig: str) -> str:
    """Restaura un placeholder y sus perturbaciones toleradas.

    Reconoce (insensible a mayúsculas): `[TAG_n]`, `**[TAG_n]**`, corchetes
    ausentes o parciales, espacios entre tag y número, `[TAG_n]s`/`[TAG_n]'s`,
    salto de línea entre tag y número, y la etiqueta traducida al inglés.
    """
    tag, num = _ph_parts(ph)
    aliases = _TAG_ALIASES.get(tag.upper(), (tag,))
    tag_alt = "(?:" + "|".join(re.escape(a) for a in aliases) + ")"
    # El número no puede ir seguido de otro dígito (evita que [NOMBRE_1] se
    # cuele dentro de [NOMBRE_10]). El sufijo plural/sajón (minúscula,
    # case-sensitive) solo se admite tras un corchete de cierre. Con corchetes
    # no se exige límite de palabra (un placeholder puede ir pegado a texto,
    # p. ej. "CP[TELÉFONO_1]"); sin corchetes sí, para no cortar palabras.
    core = tag_alt + r"[\s_]*" + re.escape(num) + r"(?!\d)"
    pat = re.compile(
        r"\*{0,2}(?:"
        + r"\[\s*" + core + r"\s*\](?-i:'s|s)?"   # [TAG_n] y [TAG_n]s
        + r"|"
        + r"\[\s*" + core                         # [TAG_n  (solo apertura)
        + r"|"
        + r"(?<![A-Za-z0-9])" + core + r"\s*\]?"  # TAG_n o TAG_n] (sin apertura)
        + r")\*{0,2}",
        re.IGNORECASE,
    )
    return pat.sub(orig, text)


def _map_bert_label(label: str) -> str:
    base = label.split("-")[-1]
    if base == "ANON":
        return "PHI"
    return BRAT_TO_UNIFIED.get(base, "OTHER")


def _map_step2_label(label: str) -> str:
    return STEP2_TO_UNIFIED.get(label, "OTHER")


# ── Regex rules (step2) ─────────────────────────────────────────────────────
PATTERNS = {
    "date": re.compile(
        r"\b(?:0[1-9]|[12]\d|3[01]|[1-9])[./-](?:0[1-9]|1[0-2]|[1-9])[./-](?:\d{4}|\d{2})\b|"
        r"\b\d{1,2}\s+de\s+\w+\s+de\s+\d{4}\b|"
        r"\b\d{1,2}\s+de\s+(?:Enero|Febrero|Marzo|Abril|Mayo|Junio|Julio|Agosto|Septiembre|Octubre|Noviembre|Diciembre|Gener|Febrer|Març|Abril|Maig|Juny|Juliol|Setembre|Octubre|Novembre|Desembre)\b|"
        r"\b(?:0[1-9]|[12]\d|3[01])[./-](?:0[1-9]|1[0-2])\b|"
        r"\b(?:0[1-9]|1[0-2])[./-]\d{2,4}\b|"
        r"\b(?:Enero|Febrero|Marzo|Abril|Mayo|Junio|Julio|Agosto|Septiembre|Octubre|Noviembre|Diciembre|Gener|Febrer|Març|Abril|Maig|Juny|Juliol|Setembre|Octubre|Novembre|Desembre)[/-]\d{2,4}\b|"
        r"\b(?:Enero|Febrero|Marzo|Abril|Mayo|Junio|Julio|Agosto|Septiembre|Octubre|Noviembre|Diciembre|Gener|Febrer|Març|Abril|Maig|Juny|Juliol|Setembre|Octubre|Novembre|Desembre)\b|"
        r"\b(?:Lunes|Martes|Miércoles|Miercoles|Jueves|Viernes|Sábado|Sabado|Domingo|Dilluns|Dimarts|Dimecres|Dijous|Divendres|Dissabte|Diumenge)\b|"
        r"\b(19|20)\d{2}\b",
        re.IGNORECASE,
    ),
    "time": re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*h?\b", re.IGNORECASE),
    # Teléfono acotado a formatos españoles/internacionales: 9 dígitos que
    # empiezan por 6/8/9, con código de país +34/0034 opcional y separadores
    # opcionales. Así no absorbe identificadores ("28 28 20943", "50 50 98653")
    # ni DNI/NHC que empiezan por otras cifras.
    "phone": re.compile(
        r"(?<!\w)(?:(?:\+34|0034)[\s.-]?)?[689](?:[\s.-]?\d){8}(?!\d)"
    ),
    "email": re.compile(
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
    ),
    "url": re.compile(
        r"\b(?:https?://|ftp://|www\.)[^\s<>\"']+"
        r"|\b[A-Za-z0-9][A-Za-z0-9.\-]*\.(?:com|es|net|org|cat|eu|edu|gov|info|biz)\b"
    ),
    "doctor": re.compile(
        r"\b(?:dr[as]?\.?|doctora?)\s*[:.]?\s+(?!(?:OI|OD|HTA|EA|AP|ANM|AMC|dret|dreta|drenaje|dren|droga|drogueta|dramático|drástica)\b)[a-zÁÉÍÓÚÑ][a-zjqñáéíóúü]+(?:\s+[a-zÁÉÍÓÚÑ][a-zjqñáéíóúü]+)*(?=[.,;?\)\]\/\s-]*|$)",
        re.IGNORECASE,
    ),
    "age": re.compile(r"\b\d{1,3}\s?(?:años?|a)\b", re.IGNORECASE),
    "location": re.compile(
        r"\b(Barcelona|Hospitalet de Llobregat|L'Hospitalet|Badalona|Terrassa|Sabadell|Mataró|Santa Coloma de Gramenet|Cornellà de Llobregat|Sant Boi de Llobregat|Sant Cugat del Vallès|Manresa|Rubí|Vilanova i la Geltrú|Viladecans|Castelldefels|Prat de Llobregat|El Prat|Granollers|Cerdanyola del Vallès|Mollet del Vallès|Vic|Esplugues de Llobregat|Gavà|Sant Feliu de Llobregat|Igualada|Vilafranca del Penedès|Ripollet|Sant Adrià de Besòs|Montcada i Reixac|Sant Joan Despí|Barberà del Vallès|Sant Pere de Ribes|Sitges|Martorell|Premià de Mar|Pineda de Mar|Sant Vicenç dels Horts|Sant Andreu de la Barca|Molins de Rei|Santa Perpètua de Mogoda|Castellar del Vallès|Olesa de Montserrat|Masnou|Esparreguera|Manlleu|Vilassar de Mar|Calella|Malgrat de Mar|Sant Quirze del Vallès|Parets del Vallès|Berga|Les Franqueses del Vallès|Caldes de Montbui|Sant Celoni|Cardedeu|Canovelles|Sant Just Desvern|Montornès del Vallès|La Garriga|Girona|Figueres|Blanes|Lloret de Mar|Olot|Salt|Palafrugell|Sant Feliu de Guíxols|Banyoles|Roses|Palamós|Santa Coloma de Farners|Torroella de Montgrí|Castelló d'Empúries|La Bisbal d'Empordà|Lleida|Tàrrega|Balaguer|Mollerussa|La Seu d'Urgell|Cervera|Solsona|Tarragona|Reus|Tortosa|El Vendrell|Cambrils|Salou|Valls|Calafell|Amposta|Vilaseca|Sant Carles de la Ràpita|La Ràpita|Torredembarra|Móra d'Ebre|Sants|Les Corts|Sarrià|Horta|Nou Barris|Sant Andreu|Sant Martí|Gràcia|Eixample|Ciutat Vella|"
        r"Antigua y Barbuda|Argentina|Bahamas|Barbados|Belice|Bolivia|Brasil|Canadá|Chile|Colombia|Costa Rica|Cuba|Dominica|Ecuador|El Salvador|Estados Unidos|Granada|Guatemala|Guyana|Haití|Honduras|Jamaica|México|Nicaragua|Panamá|Paraguay|Perú|República Dominicana|San Cristóbal y Nieves|San Vicente y las Granadinas|Santa Lucía|Surinam|Trinidad y Tobago|Uruguay|Venezuela|Puerto Rico|Guayana Francesa|Groenlandia|Bermudas)\b",
        re.IGNORECASE,
    ),
    "family_relation": re.compile(
        r"\b(madre|padre|hijo|hija|esposo|esposa|marido|mujer|hermano|hermana|tío|tía|abuelo|abuela|nieto|nieta|sobrino|sobrina|primo|prima|cuñado|cuñada|suegro|suegra|yerno|nuera|pareja|cónyuge|viejo|vieja|papá|mamá|família|familia|mare|fill|filla|espòs|marit|dona|germà|germana|oncle|tia|avi|àvia|nét|néta|nebot|neboda|cosí|cosina|cunyat|cunyada|sogre|sogra|gendre|nora|parella|cònjuge|xicot|xicota|nòvio|nòvia)\b",
        re.IGNORECASE,
    ),
    "name_upper": re.compile(r"\b[A-ZÁÉÍÓÚÑ]{3,}(?:[\s,/,-]{1,2}[A-ZÁÉÍÓÚÑ]{2,})+\b"),
    "name_mixed": re.compile(r"\b[A-ZÁÉÍÓÚÑ][a-zjqñáéíúü]+(?:[\s,/,-]{1,2}[A-ZÁÉÍÓÚÑ][a-zjqñáéíúü]+)+\b"),
    "name_single": re.compile(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúüñç]{1,}\b"),
    "address": re.compile(
        r"\b(?:Calle|Carrer|Avenida|Av\.?|Avda\.?|Paseo|Passeig|Plaza|Plaça|C\.?/?|Camino|Camí|Via|Vía|Ronda|Travesía|Travesia|Travessera|Passatge|Pasaje|Carretera|Ctra\.?)\s+"
        r"(?:(?:de|la|el|del|dels|i|y)\s+){0,2}"
        r"[A-ZÁÉÍÓÚÜ][a-záéíóúüñçàèìòù]{1,25}"
        r"(?:\s+(?:de|la|el|del|dels|i|y|san|sant|santa)\s+[A-ZÁÉÍÓÚÜ][a-záéíóúüñçàèìòù]{1,25}){0,3}"
        r"(?:,?\s*\d{1,4}(?:\s*[A-Za-z])?)?"
    ),
}

# Identificadores con formatos concretos (DNI/NIE con letra válida, NHC, CIP,
# Seguridad Social). La prioridad de la más específica se resuelve en el dedup
# por solape de `_regex_detect`.
IDENTIFIER_PATTERNS = {
    "dni": re.compile(r"\b\d{8}[A-Za-z]\b"),
    "nie": re.compile(r"\b[XYZ]\d{7}[A-Za-z]\b"),
    "ss": re.compile(r"\b\d{2}/\d{8}/\d{2}\b"),
    "cip": re.compile(r"\b[A-Z]{4}\d{10}\b"),
    "nhc_labeled": re.compile(
        r"\b(?:NHC|HC|N[ºo]\s*H[ªa]|n[ºo]\s*(?:de\s*)?(?:historia|h[ªa]|hc|hist[oò]ria))\s*[:#.\-]?\s*\d{4,11}\b",
        re.IGNORECASE,
    ),
    "nhc_22_5": re.compile(r"\b\d{2}[\s-]\d{2}[\s-]\d{5}\b"),
    "nhc_2_8_2": re.compile(r"\b\d{2}[-/]\d{7,8}[-/]\d{2}\b"),
    "plain": re.compile(r"\(?\b\d{6,10}\b\)?"),
}

_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def _valid_dni(text: str) -> bool:
    if len(text) == 9 and text[8].isalpha() and text[:8].isdigit():
        return _DNI_LETTERS[int(text[:8]) % 23] == text[8].upper()
    return False


def _valid_nie(text: str) -> bool:
    if len(text) == 9 and text[0] in "XYZ" and text[1:8].isdigit() and text[8].isalpha():
        num = int(str("XYZ".index(text[0])) + text[1:8])
        return _DNI_LETTERS[num % 23] == text[8].upper()
    return False


# Cabecera de hospital, con el nombre propio exigido en mayúscula inicial
# (case-sensitive) para no tragarse "clínica ocular" ni "hospital por dolor".
_HOSPITAL_HEAD = re.compile(
    r"\b(?:Hospital|Clínica|Complejo\s+Hospitalario|CAP|Centre|Centro\s+de\s+Salud)\b",
    re.IGNORECASE,
)
_HOSPITAL_CONN = re.compile(
    r"(?:de\s+la|del|de|la|el|los|las|i|y|San|Sant|Santa|Virgen|Marqués|Doctor|Dr\.?)\s+",
    re.IGNORECASE,
)
_TITLECASE = re.compile(r"[A-ZÁÉÍÓÚÑ][a-záéíóúüñç]+")


def _hospital_spans(text: str) -> list[tuple]:
    """Devuelve (start, end) de nombres de hospital.

    El nombre debe contener al menos una palabra en mayúscula inicial tras la
    cabecera; se extiende por conectores y palabras en mayúscula inicial, y por
    el patrón "12 de Octubre".
    """
    spans = []
    for m in _HOSPITAL_HEAD.finditer(text):
        i = m.end()
        end = m.end()
        consumed_name = False
        while i < len(text):
            j = i
            while j < len(text) and text[j].isspace():
                j += 1
            conn = _HOSPITAL_CONN.match(text, j)
            if conn:
                i = conn.end()
                continue
            wm = _TITLECASE.match(text, j)
            if wm:
                end = wm.end()
                consumed_name = True
                i = end
                continue
            dm = re.match(r"\d{1,2}\s+de\s+", text[j:])
            if dm:
                nm = _TITLECASE.match(text, j + dm.end())
                if nm:
                    end = nm.end()
                    consumed_name = True
                    i = end
                    continue
            break
        if consumed_name:
            spans.append((m.start(), end))
    return spans


# Disparadores de firma: "Remitido por:", "Emitido por:", "Fdo:", "Firmado por:".
_SIG_TRIGGER = re.compile(
    r"(?:Remitido\s+por|Emitido\s+por|Fdo|Firmado\s+por)\s*[:.]?\s*",
    re.IGNORECASE,
)

# Términos genéricos en mayúscula inicial que NO son nombres de persona
# (cabeceras, campos de plantilla, epónimos, bacterias). Lista genérica por
# categoría, no nombres concretos de dev.
_TITLECASE_STOPLIST = {
    "localidad", "provincia", "historia", "actual", "antecedentes",
    "personales", "familiares", "motivo", "consulta", "enfermedad",
    "exploración", "física", "pruebas", "complementarias", "evolución",
    "tratamiento", "diagnóstico", "diagnostico", "curso", "clínico",
    "clínica", "alergias", "hábitos", "habitos", "tóxicos", "toxicos",
    "interconsultas", "observaciones", "plan", "resumen", "cuidados",
    "intensivos", "paliativos", "neonatales", "antígeno", "prostático",
    "específico", "escherichia", "coli", "budd", "chiari", "ziehl",
    "nielsen", "melanoma", "priapismo", "remitido", "servicio", "unidad",
    "centro", "universidad", "facultad", "medicina", "odontología",
    "instituto", "hospital", "complejo", "fundación", "fundació",
}

NAME_KEYWORDS = [
    "nombre", "paciente", "contacto", "persona", "responsable", "cuidador",
    "cuidadora", "tutor", "tutora", "familiar", "madre", "padre", "hijo",
    "hija", "esposa", "esposo", "marido", "mujer", "hermano", "hermana",
    "tío", "tía", "abuelo", "abuela", "nieto", "nieta", "sobrino", "sobrina",
    "primo", "prima", "cuñado", "cuñada", "suegro", "suegra", "yerno",
    "nuera", "pareja", "cónyuge", "novio", "novia", "nom", "contacte",
    "mare", "pare", "fill", "filla", "espòs", "marit", "dona", "germà",
    "germana", "oncle", "tia", "avi", "àvia", "nét", "néta", "nebot",
    "neboda", "cosí", "cosina", "cunyat", "cunyada", "sogre", "sogra",
    "gendre", "nora", "parella", "cònjuge", "xicot", "xicota", "nòvio",
    "nòvia", "facultatiu", "profesional", "responsables", "apellidos",
    "cognoms", "valoración", "valoració",
]

MEDICAL_ACRONYMS = {
    "urología", "cardiología", "digestivo", "respiratorio", "neurología",
    "traumatología", "urgencias", "medicina", "interna", "atención",
    "primaria", "mg/dl", "mmhg", "bpm", "lpm", "sat", "o2", "pcr", "vsg",
    "hba1c", "colesterol", "hdl", "ldl", "triglicéridos", "got", "gpt",
    "ggt", "fa", "bilirrubina", "creatinina", "urea", "sodio", "potasio",
    "cloro", "calcio", "fósforo", "magnesio", "hierro", "ferritina", "tsh",
    "t4", "t3", "vitamina", "clínic", "clínico", "hospital",
    "urgències", "informe", "hcp", "trastorno", "síndrome",
    "enfermedad", "diabetes", "mellitus", "insuficiencia", "renal",
    "cardíaca", "respiratoria", "aguda", "crónica", "severa", "leve",
    "moderada", "tratamiento", "dosis", "pauta", "comprimido", "pastilla",
    "jarabe", "solución", "inyección", "vía", "oral", "intravenosa",
    "intramuscular", "subcutánea", "paciente", "usuario", "historia",
    "clínica", "alta", "ingreso", "consulta", "visita", "diagnóstico",
    "evolución", "plan", "antecedentes", "personales", "familiares",
    "quirúrgicos", "patológicos", "psiquiátricos", "alergias", "hábitos",
    "tóxicos", "exploración", "física", "constantes", "vitales", "tensión",
    "arterial", "frecuencia", "temperatura", "saturación", "oxígeno",
    "peso", "talla", "índice", "masa", "corporal", "fármaco",
    "medicamento", "principio", "activo", "posología", "abilify", "adiro",
    "aspirina", "atorvastatina", "bisoprolol", "captopril", "depakine",
    "diazepam", "enalapril", "fluoxetina", "furosemida", "ibuprofeno",
    "insulina", "lorazepam", "metformina", "metamizol", "nolotil",
    "omeprazol", "paracetamol", "plavix", "prednisona", "quetiapina",
    "salbutamol", "sintrom", "simvastatina", "trankimazin", "ventolin",
    "zolpidem",
}

ROBUST_PUNC = r"[.,;?\)\]\/\s-]*"

EXCLUDED_HEADERS = {
    "ANTECEDENTES FAMILIARES", "ANTECEDENTES PERSONALES", "MOTIVO DE CONSULTA",
    "ENFERMEDAD ACTUAL", "EXPLORACIÓN FÍSICA", "PRUEBAS COMPLEMENTARIAS",
    "EVOLUCIÓN", "TRATAMIENTO", "DIAGNOSTICO", "DIAGNÓSTICO", "CURSO CLINICO",
    "CURSO CLÍNICO", "ALERGIAS", "HABITOS TOXICOS", "HÁBITOS TÓXICOS",
    "INTERCONSULTAS", "OBSERVACIONES", "PLAN", "RESUMEN", "HISTORIA ACTUAL",
}


def _load_whitelist() -> set:
    """Carga lista_blanca.txt del proyecto (si existe)."""
    path = ROOT / "lista_blanca.txt"
    terms = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                terms.add(line.lower())
    return terms


LISTA_BLANCA = _load_whitelist()


class Anonymizer:
    """BERT (carmen) + regex detector with reversible placeholder anonymization."""

    STRIDE = 128
    BATCH_SIZE = 32

    def __init__(self, model_dir=None, device=None, threshold=0.1, use_presidio=None):
        try:
            import torch
        except ImportError as exc:
            raise ImportError("Falta PyTorch. Instala: pip install torch") from exc
        try:
            from transformers import AutoModelForTokenClassification, AutoTokenizer
        except ImportError:
            try:
                from transformers import AutoTokenizer
                from transformers.models.auto import AutoModelForTokenClassification
            except ImportError as exc:
                raise ImportError(
                    "No se pudo importar AutoModelForTokenClassification. "
                    "Reinstala transformers: pip install -U transformers"
                ) from exc

        self.model_dir = Path(model_dir) if model_dir else DEFAULT_MODEL_DIR
        self.device = device or ("cuda:0" if torch.cuda.is_available() else "cpu")
        self.threshold = threshold
        # Presidio es un extra opcional, desactivado por defecto. Se activa con
        # PUKARA_ENABLE_PRESIDIO=1 (ver .env.example): añade recall en
        # NAME/EMAIL/LOCATION y reduce el leakage a costa de bajar el F1.
        if use_presidio is None:
            raw = _read_env("PUKARA_ENABLE_PRESIDIO", "").strip().lower()
            use_presidio = raw in ("1", "true", "yes", "on")
        self.use_presidio = use_presidio

        model_path = self.model_dir / model_dirname()
        if not model_path.exists():
            raise FileNotFoundError(f"Modelo no encontrado: {model_path}")
        if not verify_model_hash(model_path):
            raise RuntimeError(
                "El hash SHA-256 del modelo BERT no coincide con BERT_MODEL_SHA256"
            )
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
        self.model = AutoModelForTokenClassification.from_pretrained(str(model_path), local_files_only=True)
        self.model.to(self.device).eval()

        # Placeholder map and counters (per request)
        self.reset()

    def reset(self):
        self.text_to_ph = {}   # real text -> placeholder (consistency)
        self.ph_to_text = {}   # placeholder -> real text (reversal)
        self.counters = {}     # tag -> counter

    # ── Detección BERT ────────────────────────────────────────────────────
    def _bert_detect(self, text: str) -> list[dict]:
        import numpy as np
        import torch

        enc = self.tokenizer(
            text,
            return_overflowing_tokens=True,
            stride=self.STRIDE,
            padding=True,
            truncation=True,
            max_length=self.tokenizer.model_max_length,
            return_offsets_mapping=True,
            return_special_tokens_mask=True,
            return_tensors="pt",
        )
        input_ids = enc["input_ids"].to(self.device)
        attention_mask = enc["attention_mask"].to(self.device)
        offset_mapping = enc["offset_mapping"]
        special_tokens_mask = enc["special_tokens_mask"]

        logits_parts = []
        with torch.no_grad():
            for i in range(0, input_ids.shape[0], self.BATCH_SIZE):
                out = self.model(
                    input_ids=input_ids[i:i + self.BATCH_SIZE],
                    attention_mask=attention_mask[i:i + self.BATCH_SIZE],
                )
                logits_parts.append(out.logits.cpu())
        logits = torch.cat(logits_parts, dim=0)
        probs = logits.softmax(dim=-1)
        scores, pred_ids = probs.max(dim=-1)

        id2label = self.model.config.id2label or {}
        label2id = self.model.config.label2id or {}
        o_id = label2id.get("O", 0)

        om = np.asarray(offset_mapping, dtype=np.int64)
        am = attention_mask.cpu().numpy().astype(bool)
        if torch.is_tensor(special_tokens_mask):
            spm = special_tokens_mask.cpu().numpy().astype(bool)
        else:
            spm = np.asarray(special_tokens_mask).astype(bool)
        pred = pred_ids.numpy()
        conf = scores.numpy()

        valid = am & ~spm & (om[:, :, 1] > om[:, :, 0]) & (pred != o_id)
        entries = []
        rows, cols = np.nonzero(valid)
        for w, t in zip(rows.tolist(), cols.tolist()):
            pid = int(pred[w, t])
            raw = id2label.get(pid)
            if raw is None:
                raw = id2label.get(str(pid), "O")
            base = raw[2:] if raw.startswith(("B-", "I-")) else raw
            entries.append((int(om[w, t, 0]), int(om[w, t, 1]), base, float(conf[w, t])))

        # Dedup by span (overlap between windows): keep best score
        best = {}
        for s, e, lab, sc in entries:
            key = (s, e)
            if key not in best or sc > best[key][3]:
                best[key] = (s, e, lab, sc)
        entries = sorted(best.values())

        # Merge contiguous tokens with the same label
        merged = []
        for s, e, lab, sc in entries:
            if merged and lab == merged[-1]["label"] and s <= merged[-1]["end"] + 1:
                merged[-1]["end"] = max(merged[-1]["end"], e)
                merged[-1]["score"] = max(merged[-1]["score"], sc)
            else:
                merged.append({"start": s, "end": e, "label": lab, "score": sc})

        entities = []
        for m in merged:
            if m["score"] < self.threshold or m["end"] <= m["start"]:
                continue
            ent_text = text[m["start"]:m["end"]]
            stripped = ent_text.strip()
            if not stripped:
                continue  # el modelo a veces predice sobre saltos de línea
            # El modelo produce fragmentos ruidosos (un dígito, "C", números
            # cortos): se descartan. Un identificador/teléfono real tiene >= 5
            # dígitos y una palabra >= 2 letras.
            if len(stripped) < 2:
                continue
            if stripped.isdigit() and len(stripped) < 5:
                continue
            if stripped.lower() in LISTA_BLANCA:
                continue
            entities.append({
                "start": m["start"], "end": m["end"],
                "label": _map_bert_label(m["label"]), "text": ent_text,
            })
        return entities

    # ── Detección regex ────────────────────────────────────────────────────
    def _regex_detect(self, text: str) -> list[dict]:
        # matches: (start, end, label, text, priority, rule). En el dedup por
        # solape gana la mayor prioridad; en caso de empate, el span más largo.
        # 5 = identificadores/contactos deterministas, 4 = teléfono/fecha/hora/
        # edad, 3 = resto de reglas, 2 = nombres, 1 = discovery.
        matches: list = []
        blocked = MEDICAL_ACRONYMS | LISTA_BLANCA

        def add(start, end, label, t, prio, rule):
            if end > start and t.strip():
                matches.append((start, end, label, t, prio, rule))

        for m in PATTERNS["date"].finditer(text):
            add(m.start(), m.end(), "DATE", m.group(), 4, "date")
        for m in PATTERNS["time"].finditer(text):
            add(m.start(), m.end(), "TIME", m.group(), 4, "time")
        for m in PATTERNS["phone"].finditer(text):
            add(m.start(), m.end(), "PHONE", m.group(), 4, "phone")
        for m in PATTERNS["email"].finditer(text):
            add(m.start(), m.end(), "EMAIL", m.group(), 5, "email")
        for m in PATTERNS["url"].finditer(text):
            add(m.start(), m.end(), "URL", m.group(), 5, "url")
        for m in PATTERNS["doctor"].finditer(text):
            add(m.start(), m.end(), "DOCTOR", m.group(), 3, "doctor")
        for m in PATTERNS["age"].finditer(text):
            add(m.start(), m.end(), "AGE", m.group(), 4, "age")
        for m in PATTERNS["location"].finditer(text):
            add(m.start(), m.end(), "LOCATION", m.group(), 3, "location")
        for m in PATTERNS["address"].finditer(text):
            add(m.start(), m.end(), "LOCATION", m.group(), 3, "address")
        for m in PATTERNS["family_relation"].finditer(text):
            add(m.start(), m.end(), "RELATION", m.group(), 3, "family_relation")
        for s, e in _hospital_spans(text):
            add(s, e, "HOSPITAL", text[s:e], 3, "hospital")

        # Identificadores con formatos concretos.
        for m in IDENTIFIER_PATTERNS["dni"].finditer(text):
            if _valid_dni(m.group()):
                add(m.start(), m.end(), "IDENTIFICADOR", m.group(), 5, "dni")
        for m in IDENTIFIER_PATTERNS["nie"].finditer(text):
            if _valid_nie(m.group()):
                add(m.start(), m.end(), "IDENTIFICADOR", m.group(), 5, "nie")
        for m in IDENTIFIER_PATTERNS["ss"].finditer(text):
            add(m.start(), m.end(), "IDENTIFICADOR", m.group(), 5, "ss")
        for m in IDENTIFIER_PATTERNS["cip"].finditer(text):
            add(m.start(), m.end(), "IDENTIFICADOR", m.group(), 5, "cip")
        for m in IDENTIFIER_PATTERNS["nhc_labeled"].finditer(text):
            add(m.start(), m.end(), "IDENTIFICADOR", m.group(), 5, "nhc_labeled")
        for m in IDENTIFIER_PATTERNS["nhc_22_5"].finditer(text):
            add(m.start(), m.end(), "IDENTIFICADOR", m.group(), 5, "nhc_22_5")
        for m in IDENTIFIER_PATTERNS["nhc_2_8_2"].finditer(text):
            add(m.start(), m.end(), "IDENTIFICADOR", m.group(), 5, "nhc_2_8_2")
        for m in IDENTIFIER_PATTERNS["plain"].finditer(text):
            t = m.group().strip("()")
            # Los números de 9 dígitos que empiezan por 6/8/9 son teléfono;
            # la regla de teléfono (más específica) los posee.
            if re.fullmatch(r"[689](?:[\s.-]?\d){8}", t):
                continue
            add(m.start(), m.end(), "IDENTIFICADOR", m.group(), 3, "plain")

        def already_marked(start, end):
            return any(s <= start and end <= e for s, e, *_ in matches)

        # Nombres precedidos por palabra clave (nombre, paciente, apellidos…).
        context_pattern = re.compile(
            r"\b(" + "|".join(NAME_KEYWORDS) + r")(?=" + ROBUST_PUNC + r"|$)",
            re.IGNORECASE,
        )
        single_context_pattern = re.compile(
            r"\b(nombre|nom|apellidos|cognoms)(?=" + ROBUST_PUNC + r"|$)",
            re.IGNORECASE,
        )
        lines = text.split("\n")
        current_pos = 0
        for line in lines:
            if context_pattern.search(line):
                for pattern_name in ["name_upper", "name_mixed"]:
                    for match in PATTERNS[pattern_name].finditer(line):
                        name = match.group()
                        if name.lower() in blocked:
                            continue
                        if pattern_name == "name_mixed" and name.lower() in NAME_KEYWORDS:
                            continue
                        start = current_pos + match.start()
                        end = current_pos + match.end()
                        if not already_marked(start, end):
                            add(start, end, "PERSON", name, 2, "name_context")
                if single_context_pattern.search(line):
                    for match in PATTERNS["name_single"].finditer(line):
                        name = match.group()
                        if name.lower() in blocked or name.lower() in NAME_KEYWORDS:
                            continue
                        if name.lower() in _TITLECASE_STOPLIST:
                            continue
                        start = current_pos + match.start()
                        end = current_pos + match.end()
                        if not already_marked(start, end):
                            add(start, end, "PERSON", name, 2, "name_single")
            current_pos += len(line) + 1

        # Nombres de firma: "Remitido por: X", "Emitido por: X", "Fdo: X".
        for sig in _SIG_TRIGGER.finditer(text):
            pos = sig.end()
            for pattern_name in ["name_mixed", "name_single"]:
                m = PATTERNS[pattern_name].match(text, pos)
                if not m:
                    continue
                name = m.group()
                if name.lower() in blocked or name.lower() in NAME_KEYWORDS:
                    break
                if pattern_name == "name_single" and name.lower() in _TITLECASE_STOPLIST:
                    break
                if not already_marked(m.start(), m.end()):
                    add(m.start(), m.end(), "PERSON", name, 2, "signature")
                break

        # MAYÚSCULAS con coma (apellidos, nombre).
        for match in PATTERNS["name_upper"].finditer(text):
            name = match.group()
            clean_name = re.sub(r"[.,;:]+$", "", name).strip()
            if "," in name and name.lower() not in blocked and clean_name not in EXCLUDED_HEADERS:
                if not already_marked(match.start(), match.end()):
                    add(match.start(), match.end(), "GENERICA", name, 2, "name_upper_comma")

        # Discovery pass: re-busca textos ya encontrados.
        discovered = set()
        for _s, _e, _lab, t, _p, _r in matches:
            clean = t.strip("()[].,;?/- ")
            if len(clean) > 3:
                discovered.add(clean)
        for t in discovered:
            pattern = re.compile(r"\b" + re.escape(t) + r"(?=" + ROBUST_PUNC + r"|$)", re.IGNORECASE)
            for match in pattern.finditer(text):
                label = "PERSON"
                for _s, _e, lab, mt, _p, _r in matches:
                    if t.lower() in mt.lower():
                        label = lab
                        break
                if not already_marked(match.start(), match.end()):
                    add(match.start(), match.end(), label, match.group(), 1, "discovery")

        # Dedup por solape: mayor prioridad gana; empate → el más largo.
        deduped = []
        for m in sorted(matches, key=lambda x: (-x[4], -(x[1] - x[0]), x[0])):
            if not any(m[0] < k[1] and k[0] < m[1] for k in deduped):
                deduped.append(m)
        deduped.sort(key=lambda x: x[0])
        entities = []
        for s, e, label, t, _p, _r in deduped:
            entities.append({
                "start": s, "end": e,
                "label": _map_step2_label(label), "text": t,
            })
        return entities

    # ── Detección combinada ────────────────────────────────────────────────
    # Clases deterministas donde la regex gana sobre BERT en caso de solape:
    # los formatos concretos (email, url, id, fecha, hora, teléfono) son más
    # fiables que las predicciones del modelo sobre el mismo span (el modelo
    # fragmenta emails y confunde NHC/DNI con teléfono). En el resto de clases
    # (NAME, LOCATION, HOSPITAL, SEX, …) gana BERT.
    _REGEX_WINS = {"EMAIL", "URL", "ID", "DATE", "TIME", "PHONE"}

    @staticmethod
    def _overlap(a, b):
        return a["start"] < b["end"] and b["start"] < a["end"]

    def detect(self, text: str) -> list[dict]:
        """BERT (base) + regex (formato determinista) + Presidio (relleno).

        Regla de desacuerdo BERT/regex sobre el mismo span (documentada en
        `docs/dev/eval-diagnosis.md`):

        - la regex gana en las clases deterministas `_REGEX_WINS`
          (EMAIL/URL/ID/DATE/TIME/PHONE), salvo que la regex diga PHONE y
          BERT diga ID (un ID no se degrada a teléfono);
        - en cualquier otra clase gana BERT.
        """
        if not text or not text.strip():
            return []
        merged = list(self._bert_detect(text))
        for e in self._regex_detect(text):
            overlaps = [m for m in merged if self._overlap(e, m)]
            if not overlaps:
                merged.append(e)
            elif (e["label"] in self._REGEX_WINS
                  and not (e["label"] == "PHONE"
                           and any(m["label"] == "ID" for m in overlaps))):
                # La regex gana: retira todos los spans BERT que solapan y
                # deja el span determinista (p. ej. un email completo frente a
                # los fragmentos que el modelo produce sobre él).
                merged = [m for m in merged if not self._overlap(e, m)]
                merged.append(e)
            # en cualquier otro caso gana BERT
        # Presidio solo rellena huecos: sus spans NAME/EMAIL/LOCATION se añaden
        # únicamente si no solapan con lo ya detectado por BERT+regex.
        if self.use_presidio:
            from . import presidio
            for e in presidio.detect_limited(text):
                if not any(self._overlap(e, m) for m in merged):
                    merged.append(e)
        merged.sort(key=lambda x: x["start"])
        return merged

    # ── Anonimización reversible ───────────────────────────────────────────
    def anonymize(self, text: str) -> str:
        for e in sorted(self.detect(text), key=lambda x: x["start"], reverse=True):
            orig = e["text"]
            ph = self.text_to_ph.get(orig)
            if ph is None:
                tag = TAGS.get(e["label"], "ANONIMO")
                n = self.counters.get(tag, 0) + 1
                self.counters[tag] = n
                ph = f"[{tag}_{n}]"
                self.text_to_ph[orig] = ph
                self.ph_to_text[ph] = orig
            text = text[:e["start"]] + ph + text[e["end"]:]
        return text

    def deanonymize(self, text: str) -> str:
        # Placeholders con número mayor primero, para no romper [NOMBRE_10]
        # al restaurar [NOMBRE_1] (además la regex exige que el número no vaya
        # seguido de más alfanuméricos).
        for ph, orig in sorted(self.ph_to_text.items(), key=lambda kv: _ph_num(kv[0]), reverse=True):
            text = _restore_placeholder(text, ph, orig)
        return text


# Lazy singleton: loaded once; optional (None if unavailable).
_ANONYMIZER = None
_ANONYMIZER_FAILED = False


def get_anonymizer():
    global _ANONYMIZER, _ANONYMIZER_FAILED
    if _ANONYMIZER is None and not _ANONYMIZER_FAILED:
        try:
            _ANONYMIZER = Anonymizer()
        except Exception as exc:  # noqa: BLE001
            _ANONYMIZER_FAILED = True
            print(f"[anonymizer] unavailable, sending without anonymization: {exc}")
    return _ANONYMIZER


if __name__ == "__main__":
    sample = (
        "Paciente: María García López, 45 años, vive en Barcelona. "
        "Teléfono 600123456. Ingresó el 12/05/2024 en el Hospital Clínic."
    )
    anon = Anonymizer()
    out = anon.anonymize(sample)
    print("Anonimizado:", out)
    print("Restaurado:", anon.deanonymize(out))
