# -*- coding: utf-8 -*-
"""Prune entities.json to IDs that appear as head_id or tail_id in release gold.

Makes intervention-type inventory match Table 2 (e.g. visual 180 -> 150).
"""
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "dataset" / "schema" / "entities.json"
SPLITS = ["train", "dev", "test"]


def main():
    used = set()
    for sp in SPLITS:
        path = ROOT / "dataset" / "benchmark" / f"{sp}.jsonl"
        for line in path.open(encoding="utf-8"):
            for g in json.loads(line).get("gold") or []:
                used.add(g.get("head_id"))
                used.add(g.get("tail_id"))
    used.discard(None)

    ents = json.loads(SCHEMA.read_text(encoding="utf-8"))
    before_ids = {e["id"] for e in ents}
    keep = [e for e in ents if e["id"] in used]
    missing = used - before_ids
    if missing:
        raise SystemExit(f"gold IDs missing from lexicon: {sorted(missing)[:20]}")

    bak = SCHEMA.with_suffix(
        f".json.bak_prune_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    shutil.copy2(SCHEMA, bak)

    ids = defaultdict(set)
    forms = Counter()
    for e in keep:
        ids[e["type"]].add(e["id"])
        forms[e["type"]] += 1

    SCHEMA.write_text(
        json.dumps(keep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"backup {bak}")
    print(f"forms {len(ents)} -> {len(keep)}; ids {len(before_ids)} -> {len({e['id'] for e in keep})}")
    for t in sorted(ids):
        print(f"  {t}: ids={len(ids[t])} forms={forms[t]}")
    inter = [
        "visual",
        "tactile",
        "auditory",
        "olfactory",
        "gustatory",
        "perceptual",
        "multiple_senses",
    ]
    print(
        "intervention",
        sum(len(ids[t]) for t in inter),
        sum(forms[t] for t in inter),
    )


if __name__ == "__main__":
    main()
