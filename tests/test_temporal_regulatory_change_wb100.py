from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from governance.regulatory_change import build_draft

def test_regulatory_draft_carries_temporal_source_snapshot():
    d = build_draft(
        {"M3.6": {"requirement": "candidate"}},
        source_title="P012-2026",
        source_reference="instrument://external/P012-2026_TRM_Consultation_Paper.pdf",
        source_id="MAS-TRM-P012-2026",
        as_of="2026-09-14",
    )
    rc = d["regulatory_change"]
    assert rc["source_id"] == "MAS-TRM-P012-2026"
    assert rc["source_snapshot"]["status"] == "proposed"
    assert rc["source_snapshot"]["normative_status"] == "consultation"
    assert rc["source_change_alerts"]
