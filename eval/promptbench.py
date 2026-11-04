"""Synthetic prompt benchmark (Phase 4.3).

Generates prompts by construction with gold spans and canonical entity ids, runs
the anonymizer (regex-only now; BERT via `--mode`), and reports span-level P/R/F1,
placeholder consistency (same entity -> same placeholder across mentions/variants)
and collision (distinct entities -> distinct placeholders).

Limitations (declared, not hidden): synthetic and templated, so it is an
optimistic upper bound; and if the templates are written by the same team that
wrote the regex rules, there is circularity. A held-out template set should not
be inspected during development.
"""
from __future__ import annotations

import argparse
import datetime
import json
import random
import subprocess
import sys
from pathlib import Path

from eval import common


# ── Deterministic entity generators (dependency-free) ─────────────────────
def _dni_letter(number: int) -> str:
    return "TRWAGMYFPDXBNJZSQVHLCKE"[number % 23]


_FIRST_NAMES = [
    "María", "Juan", "Josefina", "Pau", "Mercè", "Antoni", "Núria", "Jordi",
    "Carme", "Ramon", "Laura", "Miquel", "Anna", "Pere", "Rosa", "Josep",
    "Marta", "David", "Sara", "Marc", "Elena", "Carles", "Montserrat",
    "Xavier", "Imma",
]

_LAST_NAMES = [
    "García López", "Ferrer Puig", "Roca Soler", "Vila Serra",
    "Martí Bosch", "Puig i Cadafalch", "Serra Vives", "Costa Font",
    "Oliver Riera", "Soler Prat", "Vidal Roca", "Casas Puig", "Torres Serra",
    "Ribas Soler", "Pons Vila", "Comas Ferrer", "Dalmau Bosch", "Ferrer Roca",
    "Mas Puig", "Roig Soler", "Valls Serra", "Batlle Costa", "Font Oliver",
    "Prats Riera", "Sala Prat",
]


def make_person(rng: random.Random, i: int) -> dict:
    first = _FIRST_NAMES[i % len(_FIRST_NAMES)]
    last = _LAST_NAMES[(i * 7 + i // len(_FIRST_NAMES)) % len(_LAST_NAMES)]
    return {
        "name": f"{first} {last}",
        "lower": f"{first.lower()} {last.lower()}",
        "upper": f"{first.upper()} {last.upper()}",
        "short": f"{last.split()[0]}",
    }


def make_ids(rng: random.Random, i: int) -> dict:
    dni_num = 10_000_000 + i * 37
    return {
        "dni": f"{dni_num}{_dni_letter(dni_num)}",
        "nie": f"X{1000000 + i * 13}{_dni_letter(i * 13)}",
        "nhc": f"NHC{2000000 + i}",
        "phone": f"6{rng.randint(0, 9):01d}{rng.randint(0, 9999999):07d}",
    }


def generate_prompts(seed: int, n: int):
    """Return prompts with exact gold spans by construction.

    Each prompt is a list of segments `(text, label, entity_id)`; entity
    segments contain only the entity surface, so gold spans are exact.
    """
    rng = random.Random(seed)
    prompts = []
    for i in range(n):
        p = make_person(rng, i)
        ids = make_ids(rng, i)
        eponym = ["Crohn", "Parkinson"][i % 2]

        # Categories: clinical-note summary, email draft, SQL/CSV, informal.
        if i % 4 == 0:
            segs = [
                ("Resumen de nota clínica del paciente ", None, None),
                (p["name"], "NAME", "person"),
                (", nacido el ", None, None),
                ("03/05/1950", "DATE", "dob"),
                (", NHC ", None, None),
                (ids["nhc"], "ID", "nhc"),
                (", DNI ", None, None),
                (ids["dni"], "ID", "dni"),
                (" y teléfono ", None, None),
                (ids["phone"], "PHONE", "phone"),
                (". Ingresó en ", None, None),
                ("Barcelona", "LOCATION", "city"),
                (" el ", None, None),
                ("12 de mayo de 2024", "DATE", "admission"),
                (" con enfermedad de ", None, None),
                (eponym, "OTHER", "disease"),
                (". A la visita acude el Sr. ", None, None),
                (p["short"], "NAME", "person"),
                (", documentado como ", None, None),
                (p["upper"], "NAME", "person"),
                (".", None, None),
            ]
        elif i % 4 == 1:
            segs = [
                ("Asunto: alta de ", None, None),
                (p["name"], "NAME", "person"),
                (" (", None, None),
                (ids["dni"], "ID", "dni"),
                ("). Contactar en ", None, None),
                (ids["phone"], "PHONE", "phone"),
                (". Atentamente, ", None, None),
                ("Dr. ", None, None),
                (p["name"], "PROFESSIONAL", "person"),
                (".", None, None),
            ]
        elif i % 4 == 2:
            segs = [
                ("INSERT INTO pacientes VALUES ('", None, None),
                (p["name"], "NAME", "person"),
                ("', '", None, None),
                (ids["dni"], "ID", "dni"),
                ("', '", None, None),
                (p["lower"], "NAME", "person"),
                ("'); -- ", None, None),
                (ids["nhc"], "ID", "nhc"),
                (".", None, None),
            ]
        else:
            segs = [
                ("oye, el paciente ", None, None),
                (p["lower"], "NAME", "person"),
                (" con DNI ", None, None),
                (ids["dni"], "ID", "dni"),
                (" vino ayer, su nombre completo es ", None, None),
                (p["upper"], "NAME", "person"),
                (" y vive en ", None, None),
                ("Barcelona", "LOCATION", "city"),
                (".", None, None),
            ]

        text = "".join(s for s, _, _ in segs)
        gold = []
        mentions = {}
        pos = 0
        for surface, label, eid in segs:
            start = pos
            end = pos + len(surface)
            if label is not None:
                gold.append({"start": start, "end": end, "label": label,
                             "text": surface})
                mentions.setdefault(eid, []).append((surface, start, end, label))
            pos = end

        prompts.append({"id": i, "text": text, "gold": gold, "mentions": mentions})
    return prompts


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthetic prompt benchmark")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n", type=int, default=5000)
    parser.add_argument("--mode", choices=["regex", "bert", "combined"],
                        default="combined")
    parser.add_argument("--model-dir", default=None)
    parser.add_argument("--out", default="eval/results/promptbench.json")
    args = parser.parse_args()

    prompts = generate_prompts(args.seed, args.n)
    predictor = common.Predictor(args.mode, args.model_dir)

    strict_tp = 0
    relaxed_tp = 0
    total_gold = 0
    total_pred = 0
    consistent = 0
    consistent_total = 0
    collisions = 0

    for prompt in prompts:
        text = prompt["text"]
        gold = prompt["gold"]
        _, text_to_ph = predictor.anonymize(text)
        pred = predictor.detect(text)

        total_gold += len(gold)
        total_pred += len(pred)
        strict_tp += _count(common._span_exact, gold, pred)
        relaxed_tp += _count(common._span_overlap, gold, pred)

        # Consistency: all detected mentions of one canonical entity must share
        # exactly one placeholder.
        for _eid, mentions in prompt["mentions"].items():
            phs = {text_to_ph[s] for s, _s, _e, _l in mentions if s in text_to_ph}
            if phs:
                consistent_total += 1
                if len(phs) == 1:
                    consistent += 1

        # Collision: distinct canonical entities must map to distinct
        # placeholders.
        ph_to_eid = {}
        for eid, mentions in prompt["mentions"].items():
            for surface, _s, _e, _l in mentions:
                ph = text_to_ph.get(surface)
                if ph is not None:
                    prev = ph_to_eid.get(ph)
                    if prev is not None and prev != eid:
                        collisions += 1
                    ph_to_eid[ph] = eid

    strict = _prf(strict_tp, total_pred - strict_tp, total_gold - strict_tp)
    relaxed = _prf(relaxed_tp, total_pred - relaxed_tp, total_gold - relaxed_tp)

    result = {
        "script": "eval/promptbench.py",
        "generated": datetime.datetime.utcnow().isoformat() + "Z",
        "code_revision": _git(),
        "environment": common.environment(),
        "mode": args.mode,
        "seed": args.seed,
        "n_prompts": len(prompts),
        "span_strict": strict,
        "span_relaxed": relaxed,
        "coreference": {
            "consistent_entities": consistent,
            "total_entities_with_detected_mentions": consistent_total,
            "consistency_rate": round(_div(consistent, consistent_total), 4),
        },
        "collisions": collisions,
        "limitations": [
            "Synthetic and templated: optimistic upper bound.",
            "Potential circularity if templates and regex rules share authors.",
        ],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(
        f"[promptbench] {len(prompts)} prompts. relaxed F1={relaxed['f1']:.4f}, "
        f"consistency={result['coreference']['consistency_rate']:.4f}"
    )
    return 0


def _count(matcher, gold, pred):
    matched_gold = set()
    matched_pred = set()
    for gi, g in enumerate(gold):
        for pi, p in enumerate(pred):
            if pi in matched_pred:
                continue
            if matcher(g, p):
                matched_gold.add(gi)
                matched_pred.add(pi)
                break
    return len(matched_gold)


def _prf(tp, fp, fn):
    p = _div(tp, tp + fp)
    r = _div(tp, tp + fn)
    f1 = _div(2 * p * r, p + r)
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4)}


def _div(a, b):
    return a / b if b else 0.0


def _git():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=common.ROOT, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())
