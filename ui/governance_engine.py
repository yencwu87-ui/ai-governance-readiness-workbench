"""GE-116 page-level projection for the governance engine."""
from __future__ import annotations

from governance.resources import Resource, ResourceSelector
from governance.specs import control_predicate_specs, predicate_spec_hash
from governance.semantic_registry import control_semantics
from governance.predicate_coverage import coverage


def render(st, *, control, service, observations, capabilities):
    resource = Resource(
        resource_id=str(control.id),
        resource_class="control",
        attributes={"framework": control.lib, "control_id": control.id},
        tags=(),
    )
    plan_result, selected = service.verification_plan(
        control_id=control.id,
        resources=[resource],
        selector=ResourceSelector(resource_ids=(resource.resource_id,)),
        available_capabilities=capabilities,
    )

    cov = coverage()
    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Governed controls", cov.get("controls", 0))
    g2.metric("Semantic elements", cov.get("semantic_elements", 0))
    g3.metric("Deterministic", cov.get("deterministic_elements", 0))
    g4.metric("Human judgement", cov.get("human_judgement_elements", 0))
    st.caption("Semantic coverage means every governed element has an explicit reviewer-facing meaning and verification classification. It does not imply every element is executable automatically.")

    st.markdown("### Verification plan")
    c1, c2, c3 = st.columns(3)
    c1.metric("Resources selected", len(selected))
    c2.metric("Requirements", len(plan_result.requirements))
    c3.metric("Missing capabilities", len(plan_result.missing_capabilities))
    st.caption(f"Plan hash: `{plan_result.plan_hash[:16]}`")
    if plan_result.missing_capabilities:
        st.warning("Missing verification capabilities: " + ", ".join(plan_result.missing_capabilities))
    if plan_result.requirements:
        st.dataframe([
            {"Element": q.element_id, "Verification": q.verification,
             "Evidence": ", ".join(q.evidence_types), "Capabilities": ", ".join(q.capability_hints)}
            for q in plan_result.requirements
        ], width="stretch", hide_index=True)

    semantic = control_semantics(control.id, control.lib)
    st.markdown("### Governed semantic coverage")
    if not semantic:
        st.error("No semantic registry entry exists for this governed control.")
        return
    st.caption("Every governed element has a reviewer-facing intent, evidence expectation, applicability and verification classification. Deterministic predicates are shown separately.")
    st.dataframe([
        {"Element": e.get("id"), "Requirement": e.get("governed_text"), "Intent": e.get("intent"),
         "Verification": e.get("verification"), "Applicability": e.get("applies_when") or "Always",
         "Evidence": "; ".join(e.get("expected_evidence") or []) or "See design-test guidance",
         "Source": e.get("source_grounding"),
         "Predicate": ", ".join(e.get("predicate_spec", {}).get("element_predicates") or []) or "—"}
        for e in semantic.get("elements") or []
    ], width="stretch", hide_index=True)

    # Element blocks keep the governed sentence visible instead of reducing the semantic layer
    # to a title-only table. This makes D1.3.e1-e4 and similarly decomposed controls inspectable.
    st.markdown("### Element detail")
    for e in semantic.get("elements") or []:
        label = f'{e.get("id", "element")}: {e.get("governed_text", "")}'
        with st.expander(label, expanded=False):
            st.write(e.get("intent") or "")
            m1, m2, m3 = st.columns(3)
            m1.write(f'**Verification**\n{e.get("verification", "—")}')
            m2.write(f'**Applicability**\n{e.get("applies_when") or "Always"}')
            m3.write(f'**Source**\n{e.get("source_grounding", "—")}')
            evidence = e.get("expected_evidence") or []
            if evidence:
                st.write("**Expected evidence**")
                for item in evidence:
                    st.markdown(f"- {item}")
            pred = e.get("predicate_spec", {}).get("element_predicates") or []
            st.caption("Predicate: " + (", ".join(pred) if pred else "—"))

    specs = control_predicate_specs(control.id, control.lib)
    st.markdown("### Governed predicate specification")
    if not specs:
        st.info("No deterministic predicate specification is registered for this control. Human-judgement verification remains explicit rather than being replaced by a generic predicate.")
        return
    st.caption(f"Specification hash: `{predicate_spec_hash(control.id, control.lib)[:16]}`")
    st.dataframe([
        {"Element": eid, "Observability": spec.get("observability", "ordinary"),
         "Predicates": ", ".join(str(p.get("name")) for p in spec.get("predicates", [])),
         "Conditional": "yes" if spec.get("applicability") else "no"}
        for eid, spec in sorted(specs.items()) if spec.get("observability") != "out_of_band"
    ], width="stretch", hide_index=True)

    st.markdown("### Observations")
    if not observations:
        st.info("No canonical observations are stored for this control yet. Collect a plugin observation in Review → Evidence.")
        return
    st.caption(f"{len(observations)} canonical observation(s) available from the current plugin collection.")
    st.dataframe([
        {"Observation": o.observation_id, "Source": o.source, "Subject": o.subject,
         "Observed": o.observed_at, "Freshness": "known" if o.freshness_known else "unknown"}
        for o in observations
    ], width="stretch", hide_index=True)

    st.markdown("### Deterministic evaluation")
    result = service.deterministic_evaluate(
        control=control,
        resource_id=resource.resource_id,
        observations=observations,
    )
    st.metric("ControlResult", result.status)
    st.caption("The page renders the governed result; it does not execute predicates or calculate outcomes.")
    st.dataframe([
        {"Element": e.element_id, "Status": e.status, "Applicability": e.applicability,
         "Reasons": ", ".join(e.reason_codes)}
        for e in result.element_results
    ], width="stretch", hide_index=True)

    with st.expander("ControlResult lineage"):
        st.json(result.to_dict())
