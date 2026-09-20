# Diagnóstico de evaluación (Fase C) — MEDDOCAN dev

**Fecha:** 2026-09-19. **Partición:** `dev` (250 documentos). `test` no se toca.
Evidencia generada por `eval/diagnose.py` → `eval/results/diagnosis.json`.

## 1. Confusión ID/PHONE

Matriz de confusión gold → pred (clase del primer span predicho que solapa),
clase **ID** (soporte en dev: 745):

| Pred | Antes | Después |
|---|---|---|
| ID | 7 | **710** |
| PHONE | 715 | **13** |
| (FN) | 13 | 12 |
| SEX | 7 | 7 |
| otros | 2 | 3 |

**Causa raíz (dos mecanismos):**

1. La regex de teléfono `[3456789](?:[\s.-]?\d){8}` absorbía identificadores con
   formato "XX XX NNNNN" (`28 28 20943`, `50 50 98653`) porque son 9 dígitos con
   separadores que empiezan por 3–9.
2. El modelo BERT etiqueta NHC/DNI como `NUMERO_TELEFONO` (PHONE); la regex de
   identificador sí los detectaba como ID, pero `detect()` descartaba la regex
   porque BERT ganaba todos los solapes.

**Corrección:** regex de teléfono acotada a 9 dígitos que empiezan por 6/8/9
(con `+34`/`0034` opcional); identificadores con formatos concretos (DNI/NIE con
letra válida, NHC etiquetado, "XX XX NNNNN", "XX-NNNNNNNN-XX", CIP, SS,
plain 6–10 dígitos); prioridad de la regla más específica en el dedup; y regla
de desacuerdo BERT/regex (ver §6). El residual `ID → SEX` (7) corresponde a
errores de anotación del propio gold (`lactante`, `blanca`, …) y a un puñado de
nombres que BERT etiqueta SEX.

## 2. NAME con recall bajo

Falsos negativos de NAME en dev: **85 → 8**.

Clasificación de los 85 originales y arreglo genérico aplicado:

| Categoría | Ejemplo (ilustrativo) | Arreglo genérico |
|---|---|---|
| Nombre de firma tras "Remitido por/Emitido por/Fdo" | "Rodrigo Martínez Mansur" | Disparadores de firma → `name_mixed`/`name_single` |
| "Doctor/Dr:" con dos puntos | "Doctor Pablo Garrido Abad" | Patrón `doctor` extendido a `Doctor`/`Dr:`/`Dra:` |
| Nombre suelto tras "Nombre:" | "Pedro" | `name_single` en líneas con `nombre/nom/apellidos/cognoms` |
| Nombre truncado por OCR/segmentación | "rancisco Javier Candel" | Fuera de alcance (no se añaden nombres concretos) |

Los 8 FN restantes son firmas sin disparador estándar y 2 nombres sueltos fuera
de contexto. **No se añade ningún nombre concreto de `dev` a ninguna lista**
(regla del protocolo).

## 3. Lista blanca (`lista_blanca.txt`)

Revisada término a término. **Eliminado:**

- `ANA` — nombre de pila «Ana»; bloqueaba la anonimización de pacientes llamadas
  Ana. El concepto clínico queda cubierto por `anticuerpos antinucleares` (que
  se conserva).

No hay más apellidos, topónimos ni identificadores en la lista: `barcelona`,
`Hamilton` y `Young` ya se retiraron en la primera pasada. Los acrónimos de
2–3 letras (`RE`, `VO`, `OD`, `EA`, `FA`, `AP`, `AB`, `NP`, `TB`, `DM`, `HTA`,
`EPS`, `PV`) se conservan: son abreviaturas clínicas y los patrones de nombre
exigen ≥ 3 mayúsculas o ≥ 2 palabras, por lo que no pueden confundirse con un
nombre.

## 4. Sobre-redacción

% de tokens no-PHI alterados (combinado, dev): **2,3 % → 1,7 %**.

- La regex de hospital ahora exige nombre propio en mayúscula inicial
  (case-sensitive) tras la cabecera, elimina `H.` (capturaba «H. pylori») y
  añade `Complejo Hospitalario`/`Centro de Salud` (mejora recall de HOSPITAL).
- `name_single` (nueva) solo dispara en líneas con `nombre/nom/apellidos/cognoms`.
- Nota: el conteo por regla de `eval/diagnose.py` es *raw firing* y sobreestima
  `name_single`/`name_mixed` porque no reproduce su gating de contexto; la cifra
  real es la tasa combinada de 1,7 %.

## 5. Cambios del detector (`src/anonymizer.py`)

- `phone`: acotada a formatos españoles/internacionales (9 dígitos 6/8/9).
- `IDENTIFIER_PATTERNS`: DNI/NIE con letra válida, SS, CIP, NHC etiquetado,
  NHC "XX XX NNNNN" y "XX-NNNNNNNN-XX", y fallback `plain` (6–10 dígitos, sin
  los que parecen teléfono).
- `_hospital_spans`: cabecera + nombre propio case-sensitive.
- `doctor`: `Doctor`/`Dr:`/`Dra:`.
- Nombres: disparadores de firma y `name_single` en líneas de nombre.
- Dedup por **prioridad** (más específica gana), no por longitud.
- `detect()`: regla de desacuerdo BERT/regex (ver §6) + Presidio opcional.
- `deanonymize` sigue con `str.replace` hasta la Fase D (fuera del alcance de
  este diagnóstico).

## 6. Regla de desacuerdo BERT/regex (documentada)

Cuando BERT y regex discrepan en la etiqueta sobre el mismo span:

- La **regex gana** en las clases deterministas `{EMAIL, URL, ID, DATE, TIME,
  PHONE}`: los formatos concretos son más fiables que el modelo (que fragmenta
  emails y confunde NHC/DNI con teléfono). Excepción: si la regex dice PHONE y
  BERT dice ID, gana BERT (un ID no se degrada a teléfono).
- **BERT gana** en el resto (NAME, LOCATION, HOSPITAL, SEX, AGE, …), donde es
  más fiable que las reglas.

## 7. Ablación y decisión (dev, 250 documentos)

| Configuración | F1 relajado | Word F1 | Neutr. | Leakage amplio | Leakage directo |
|---|---|---|---|---|---|
| regex | 0,7278 | 0,7080 | 0,6509 | 0,828 | 0,820 |
| bert | 0,7472 | 0,8280 | 0,7711 | 0,788 | 0,780 |
| **bert + regex** | **0,7997** | **0,8548** | 0,9083 | 0,104 | 0,068 |
| bert + regex + Presidio | 0,7478 | 0,8198 | **0,9502** | **0,084** | **0,048** |

Con el criterio del protocolo (F1 relajado en dev, leakage amplio de desempate),
la configuración congelada es **BERT + regex** (sin Presidio). Presidio baja la
F1 por sobre-redacción de `es_core_news_lg`; como el caso de uso de Pukara asume
texto ya pseudoanonimizado, la mejora marginal de leakage no compensa. Presidio
queda como **extra accionable** (`PUKARA_ENABLE_PRESIDIO=1`) y como **baseline
standalone** (Fase F2).

## 8. Presidio (extra accionable)

- `src/presidio.py` carga spaCy `es_core_news_lg` de forma perezosa.
- Integración limitada a `NAME`/`EMAIL`/`LOCATION`, solo rellena huecos.
- Cambio medido en dev: neutralización 90,8 % → 95,0 %, leakage amplio
  10,4 % → 8,4 %, a costa de F1 relajado 0,80 → 0,75.
