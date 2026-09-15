"""Coverage views for semantic definitions and executable predicates."""
from __future__ import annotations
from governance.semantic_registry import load_semantic_registry


def coverage() -> dict:
    data = load_semantic_registry()
    controls = data.get("controls") or []
    out = {
        "schema_version": data.get("schema_version"),
        "controls": len(controls),
        "elements": 0,
        "semantic_elements": 0,
        "deterministic_elements": 0,
        "human_judgement_elements": 0,
        "out_of_band_elements": 0,
        "source_review_required_elements": 0,
        "instrument_candidate_elements": 0,
        "internal_governed_source_elements": 0,
        "control_rows": [],
    }
    for c in controls:
        es = c.get("elements") or []
        row = {"framework": c.get("framework"), "control_id": c.get("control_id"),
               "title": c.get("title"), "elements": len(es),
               "deterministic": 0, "human_judgement": 0, "out_of_band": 0,
               "source_review_required": 0, "semantic_status": c.get("semantic_status")}
        for e in es:
            out["elements"] += 1
            out["semantic_elements"] += 1
            v = str(e.get("verification") or "HUMAN_JUDGEMENT")
            if v == "DETERMINISTIC": out["deterministic_elements"] += 1; row["deterministic"] += 1
            elif v == "OUT_OF_BAND": out["out_of_band_elements"] += 1; row["out_of_band"] += 1
            else: out["human_judgement_elements"] += 1; row["human_judgement"] += 1
            g = str(e.get("source_grounding") or "")
            if g == "SOURCE_REVIEW_REQUIRED": out["source_review_required_elements"] += 1; row["source_review_required"] += 1
            elif g == "INSTRUMENT_MATCH_CANDIDATE": out["instrument_candidate_elements"] += 1
            elif g == "INTERNAL_GOVERNED_SOURCE": out["internal_governed_source_elements"] += 1
        out["control_rows"].append(row)
    return out
