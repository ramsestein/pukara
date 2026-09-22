# Pukara evaluation pipeline.
# `make eval` regenera docs/metrics.md desde eval/results/*.json.
# MEDDOCAN test (Pukara) está congelado: meddocan.json NO se re-ejecuta (ver
# docs/dev/handoff.md). Las ejecuciones sobre test (Presidio standalone y
# sobre-redacción) son de una sola vez: `make eval-test-frozen`.

SEED ?= 42
BOOTSTRAP ?= 1000

.PHONY: eval eval-full eval-test-frozen eval-regex generate-metrics clean

## Pipeline reproducible (no re-ejecuta MEDDOCAN test de Pukara).
eval: eval-full generate-metrics

eval-full:
	python -m eval.carmen --corpus data/carmen --mode combined \
		--out eval/results/carmen_pukara.json --bootstrap $(BOOTSTRAP) --seed $(SEED)
	python -m eval.carmen --corpus data/carmen --mode presidio \
		--out eval/results/presidio_carmen.json --bootstrap $(BOOTSTRAP) --seed $(SEED)
	python -m eval.carmen --corpus data/carmen --mode presidio_es \
		--out eval/results/presidio_es_carmen.json --bootstrap $(BOOTSTRAP) --seed $(SEED)
	python -m eval.promptbench --mode combined \
		--out eval/results/promptbench.json --seed $(SEED)
	python -m eval.promptbench_heldout
	python -m eval.utility --corpus data/meddocan/corpus --mode combined \
		--out eval/results/utility.json
	python -m eval.cost --corpus data/meddocan/corpus --mode combined \
		--out eval/results/cost.json
	python -m eval.over_redaction --corpus data/meddocan/corpus --split dev \
		--mode combined --breakdown --out eval/results/over_redaction_dev.json

## Ejecuciones sobre test de una sola vez (documentadas en el handoff).
eval-test-frozen:
	python -m eval.meddocan --corpus data/meddocan/corpus --split test --mode presidio \
		--out eval/results/presidio_meddocan.json --bootstrap $(BOOTSTRAP) --seed $(SEED)
	python -m eval.meddocan --corpus data/meddocan/corpus --split test --mode presidio_es \
		--out eval/results/presidio_es_meddocan.json --bootstrap $(BOOTSTRAP) --seed $(SEED)
	python -m eval.over_redaction --corpus data/meddocan/corpus --split test \
		--mode combined --out eval/results/over_redaction_test.json \
		--bootstrap $(BOOTSTRAP) --seed $(SEED)
	python -m eval.over_redaction --corpus data/meddocan/corpus --split test \
		--mode presidio --out eval/results/over_redaction_test_presidio.json \
		--bootstrap $(BOOTSTRAP) --seed $(SEED)
	python -m eval.over_redaction --corpus data/meddocan/corpus --split test \
		--mode presidio_es --out eval/results/over_redaction_test_presidio_es.json \
		--bootstrap $(BOOTSTRAP) --seed $(SEED)

## Ablación regex-only en dev (sin modelo).
eval-regex:
	python -m eval.meddocan --corpus data/meddocan/corpus --split dev --mode regex \
		--out eval/results/ablate_dev_regex.json --bootstrap $(BOOTSTRAP) \
		--seed $(SEED)

generate-metrics:
	python -m eval.generate_metrics

clean:
	rm -f eval/results/*.json docs/metrics.md

