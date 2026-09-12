from demo_evidence import generate_pack


def test_demo_pack_covers_all_195_controls(tmp_path):
    out = generate_pack(tmp_path / "demo", scenario="mixed")
    files = [p for p in out.rglob("*.md")]
    assert len(files) == 195
    assert not list(out.rglob(".demo_manifest.json")) or (out / ".demo_manifest.json").exists()
    text = next(out.rglob("*.md")).read_text(encoding="utf-8")
    assert "SYNTHETIC DEMO EVIDENCE" in text


def test_demo_pack_has_explicit_provenance(tmp_path):
    out = generate_pack(tmp_path / "demo", scenario="mixed")
    for p in list(out.rglob("*.md"))[:10]:
        text = p.read_text(encoding="utf-8")
        assert "It is synthetic fixture data" in text
        assert "NOT REAL ORGANISATIONAL EVIDENCE" in text
