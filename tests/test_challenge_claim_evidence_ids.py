from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import challenge as CH


def test_claim_vet_assigns_stable_evidence_ids_for_multiple_quotes(monkeypatch):
    monkeypatch.setattr(CH, "parse_evidence_sources", lambda text: [{"source": "test", "locator": "line:1", "quote": "quote one"}, {"source": "test", "locator": "line:2", "quote": "quote two"}])
    monkeypatch.setattr(CH, "build_pointer", lambda quote, sources, claim=None: {"quote": quote})
    monkeypatch.setattr(CH, "_requirement_pointer_context", lambda control_id, framework: ("req", [{"id": "e1", "text": "element"}], {}, "test"))

    parsed = {
        "claims": [{
            "claim_id": "C1",
            "claim": "The control is evidenced.",
            "element_id": "e1",
            "reviewer_position": "met",
            "evidence_assessment": "supported",
            "evidence_reason": "Two supplied facts support the claim.",
            "evidence_quotes": ["quote one", "quote two"],
            "confidence": "high",
        }]
    }

    rows = CH._normalise_claim_vet(parsed, "quote one\nquote two", "M3.12", "MAS")

    assert rows[0]["evidence_ids"] == [
        CH.evidence_id("supplied_evidence", "1", "quote one"),
        CH.evidence_id("supplied_evidence", "2", "quote two"),
    ]
