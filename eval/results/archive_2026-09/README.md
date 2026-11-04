# Resultados archivados (septiembre de 2026, v1.2.0)

Copia de `eval/results/*.json` tal como estaban antes de la re-ejecución de
noviembre de 2026 (v1.2.1). **No deben citarse.**

## Por qué se sustituyeron

Las ejecuciones con BERT de septiembre se hicieron en un entorno cuyas versiones
de librerías no se registraron y en el que **BERT solo procesó la primera
ventana de 512 tokens de cada documento**; a partir de ahí solo actuaban las
reglas. 166 de los 250 documentos de MEDDOCAN test superan los 512 tokens.

Evidencia (MEDDOCAN test, `meddocan.json`):

- Con el código y el modelo (SHA-256 `a8b2976c…`) idénticos, forzar que BERT vea
  solo la primera ventana reproduce el JSON archivado: F1 por palabra 84,42 %
  (archivado 84,43 %), 5.013 anotaciones neutralizadas (5.015), y fuga directa
  y amplia en **los mismos 18 y 28 documentos**.
- En el JSON archivado, las anotaciones situadas tras ~300 palabras de clases
  que solo detecta BERT (nombres de personal sanitario, calles, hospitales,
  territorios) se omitían en ≈49 %, frente a 6,6 % antes del corte.
- Con todas las ventanas (transformers 5.22.1): F1 por palabra 88,49 %, 5.292
  neutralizadas, fuga directa en 4 documentos.

La configuración del detector (regex, umbral, lista blanca, mapeo) no cambió:
`tests/test_frozen_detector.py` lo verifica contra `eval-frozen-v2`.

## Qué se ha cambiado para que no se repita

- `Anonymizer.check_bert_coverage` bloquea (fail-closed) cualquier texto que las
  ventanas de BERT no cubran por completo, en producción y en el evaluador.
- `requirements-client.lock` fija el entorno de referencia.
- Cada JSON de resultados registra las versiones en `environment`.

Nota: `utility.json` archivado se generó con el árbol sucio (`dirty: true`).
