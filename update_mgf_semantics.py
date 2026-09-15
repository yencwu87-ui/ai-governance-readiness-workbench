from pathlib import Path
import yaml, hashlib, copy, json

ROOT=Path('/mnt/data/work_fullcov')
contract_p=ROOT/'governance/knowledge/contracts/mgf_agentic.yaml'
registry_p=ROOT/'governance/knowledge/semantic_registry.yaml'

E={
'D1.1':[
('Use-case suitability is assessed against defined suitability and impact criteria before development or deployment decisions are made.',['approved suitability methodology','use-case assessment record']),
('Unsuitable or prohibited high-impact use cases are explicitly identified and excluded or escalated.',['exclusion criteria','risk decision / escalation record']),
('The assessment considers the agent’s actual autonomy, tools, data access and area of impact rather than an abstract model description.',['use-case scope','architecture / capability inventory']),
('The suitability decision and its rationale are recorded before the agent is approved for build or deployment.',['dated suitability decision','approval record']),
],
'D1.2':[
('An approved methodology for tiered risk classification exists with defined criteria.',['approved tiering methodology','classification template']),
('Tier or outcome thresholds are stated by rule rather than by unaided judgement.',['tier rules / thresholds']),
('The risk assessment is completed before the decision it informs.',['dated assessment','decision / approval record']),
('The classification outcome is approved by a role independent of the requester.',['independent approval record']),
('Each classification outcome activates a defined set of controls or gates.',['tier-to-control matrix','control/gate mapping']),
('Reassessment triggers are defined and the organisation can detect when they occur.',['reassessment criteria','change / incident monitoring record']),
],
'D1.3':[
('The permitted tools and systems available to the agent are explicitly bounded to the minimum required for the intended task.',['approved tool/system scope','architecture / access configuration']),
('The agent’s permitted level of autonomy is explicitly bounded by workflow, protocol, task or approval rules.',['autonomy boundary','workflow / SOP / protocol']),
('The agent’s area of impact is contained so failures cannot propagate beyond the approved scope.',['containment architecture','network/data/environment boundary']),
('Agent limits are enforced by design, preferably through deterministic technical controls, with additional oversight where limits are less reliable.',['technical guardrails','control test record','oversight design']),
],
'D1.4':[
('Reachable systems and data stores are explicitly identified for the agent.',['system/data access inventory']),
('Access follows least privilege and grants only the minimum permissions necessary for the task.',['permission matrix','role/access configuration']),
('High-risk write, transaction or external-impact capabilities are separately constrained or require stronger approval.',['write-path controls','approval gate configuration']),
('Changes to the agent’s access scope are controlled, approved and reviewable.',['access-change record','periodic access review']),
],
'D1.5':[
('Each agent has a unique and verifiable identity.',['agent identity record','identity configuration']),
('The identity is linked to the accountable human, organisation or supervising agent under whose authority it operates.',['authority binding','supervisory assignment']),
('Capabilities, limits, authorised action domains and escalation authority are recorded against the agent identity.',['agent identity card / registry','permission profile']),
('Material agent actions can be attributed to the agent identity and the authority under which the action occurred.',['action log','trace / audit record']),
],
'D1.6':[
('External agents, third-party agentic services and peer agents that can affect the use case are identified.',['dependency inventory','third-party agent register']),
('Risks inherited from external or peer agents are assessed, including opacity, failure propagation and permission dependencies.',['dependency risk assessment','vendor assurance']),
('Interfaces, shared data, delegated permissions and hand-offs between agents are explicitly bounded.',['interface contract','data/permission flow','delegation rules']),
('Where external components cannot provide sufficient transparency or control, compensating containment, oversight or escalation is defined.',['compensating controls','escalation / exception record']),
],
'D2.1':[
('Responsibilities for agent design, deployment, operation, oversight and escalation are explicitly allocated.',['RACI / responsibility matrix','operating model']),
('A named accountable owner remains answerable for consequential agent actions and decisions.',['named owner record','accountability assignment']),
('Responsibilities across internal teams and relevant external parties are reconciled so no material responsibility falls between organisational boundaries.',['value-chain responsibility map','third-party responsibility clauses']),
],
'D2.2':[
('Changes in agent capability, autonomy, tools, data access, use context or external dependencies are identified as governance signals.',['change taxonomy','change monitoring record']),
('Defined change signals trigger governance reassessment, approval or control updates.',['change thresholds','reassessment workflow']),
('Governance ownership and review cadence remain current as agent capabilities and risk evolve.',['governance review cadence','updated approvals / decisions']),
],
'D2.3':[
('Significant checkpoints and action boundaries requiring human approval are explicitly defined.',['checkpoint matrix','workflow design']),
('The agent cannot perform actions beyond those checkpoints without the required human approval.',['approval gate configuration','negative-path test']),
('Checkpoint design covers consequential actions such as sensitive data access, external communication or material transactions where applicable.',['action classification','checkpoint mapping']),
('Human approvals are attributable to the approver and linked to the agent action being authorised.',['approval record','agent action trace']),
],
'D2.4':[
('Approval requests present the approver with the context and risk information needed to make an informed decision.',['approval UI / request payload','risk context']),
('Approval requires an explicit decision rather than passive acknowledgement or automatic acceptance.',['approval workflow','decision log']),
('The design addresses automation bias and prevents routine approvals from becoming uncritical rubber-stamping.',['oversight controls','approval-quality review']),
('Where an approver cannot make a sound decision, the workflow provides clarification or escalation rather than forcing approval.',['escalation path','exception handling']),
],
'D2.5':[
('The organisation defines how the effectiveness of human approvals will be measured or reviewed.',['approval effectiveness criteria','QA rubric']),
('Approval activity is periodically sampled or audited for evidence of meaningful review.',['approval samples','audit record']),
('Material failures in approval effectiveness produce corrective action, escalation or re-design of the checkpoint.',['approval finding','escalation / control-change record']),
],
'D2.6':[
('The organisation identifies indicators that human attention or judgement is degrading or becoming overly reliant on agent output.',['automation-bias indicators','monitoring criteria']),
('Oversight roles are trained and designed to maintain active review rather than merely confirm agent recommendations.',['training material','oversight procedure']),
('Detected automation-bias or attention-degradation signals trigger intervention, escalation or workflow change.',['alert / intervention record','control-change record']),
],
'D2.7':[
('Users are informed of the agent’s role, capabilities and material limitations relevant to their decisions.',['user notice','capability/limitation statement']),
('User responsibilities for reviewing, approving, escalating or correcting agent output are explicit.',['user operating guidance','responsibility statement']),
('Users have a clear route to challenge, report or escalate problematic agent behaviour.',['feedback / complaint channel','escalation procedure']),
],
'D3.1':[
('Runtime tool and data access is restricted to an explicit allow-list or equivalent governed scope.',['runtime allow-list','tool/data permission configuration']),
('Least-privilege permissions are enforced at the tool or access-control layer rather than only through instructions.',['access-control policy','technical enforcement test']),
('Sensitive write, transaction or external-impact actions receive stricter controls or approval where warranted.',['write controls','high-risk tool gate']),
('Runtime tool/data access and material denials or exceptions are attributable and reviewable.',['tool-call log','access-denial log']),
],
'D3.2':[
('High-risk or untrusted agent execution occurs within an appropriately isolated environment.',['sandbox architecture','environment configuration']),
('Network, filesystem, credentials and data access are constrained to the approved execution boundary.',['network policy','filesystem/data policy','credential scope']),
('Escape paths from the sandbox or containment boundary are controlled and tested.',['sandbox escape tests','security test results']),
('Sandbox controls are re-tested when material components, tools or permissions change.',['change-triggered test record','security regression results']),
],
'D3.3':[
('Tool interfaces enforce structured inputs, permitted parameters and valid action scopes.',['tool schema','input validation rules']),
('Unauthorised or non-existent tools cannot be invoked successfully by the agent.',['tool allow-list','negative-path tests']),
('Higher-risk tool calls have stronger approval, confirmation or policy controls.',['risk-tiered tool policy','approval configuration']),
('Tool calls, failures and denied calls are logged with sufficient attribution for review.',['tool-call trace','denied-call log']),
],
'D3.4':[
('Where planning is used, the agent produces a plan or action sequence that can be inspected before execution.',['plan trace','workflow record']),
('The plan is checked against user instructions, policy and authorised scope before material execution.',['plan validation rule','policy check result']),
('Material plan deviations are surfaced rather than silently executed.',['plan-difference log','exception signal']),
('Users or reviewers can clarify or amend plans before consequential execution where appropriate.',['plan review interface','approval / edit record']),
],
'D3.5':[
('The agent has a governed mechanism for resolving task scope and instruction ambiguity before consequential execution.',['instruction interpretation procedure','scope check']),
('Ambiguous, conflicting or underspecified instructions are surfaced to the user or reviewer.',['ambiguity signal','clarification record']),
('Execution is withheld or escalated when the agent cannot establish an authorised task scope.',['stop/escalation behaviour','negative-path test']),
],
'D3.6':[
('Material agent plans, intentions or reasoning traces needed for assurance are recorded at the required level.',['plan/reasoning log','trace specification']),
('Recorded traces are attributable, time-bound and protected against unauthorised alteration.',['trace integrity controls','timestamp/identity metadata']),
('Retention and access rules allow authorised reviewers to inspect the traces needed for governance and incident analysis.',['retention policy','review access controls']),
],
'D3.7':[
('Material risk controls use structural or rule-based enforcement where a deterministic control is feasible.',['rule/guardrail specification','control architecture']),
('Controls that prevent prohibited actions are enforced below the prompt/instruction layer so they cannot be bypassed merely by rephrasing instructions.',['access-control implementation','bypass test']),
('Deterministic controls have explicit test cases demonstrating both allowed and disallowed behaviour.',['control test suite','test results']),
],
'D3.8':[
('Pre-deployment testing covers the agent capabilities, tools, workflows and risk boundaries that will operate in production.',['pre-deployment test plan','test scope']),
('Testing covers task execution, policy adherence and tool-use accuracy for the intended use case.',['task tests','policy tests','tool-use tests']),
('Adversarial and difficult scenarios are included where the risk profile warrants them.',['red-team scenarios','adversarial test results']),
('Testing uses representative environments, data or realistic simulations without prematurely exposing live impact.',['test environment','dataset / simulation record']),
('Release acceptance criteria are defined in advance and failures are dispositioned before deployment.',['pre-registered thresholds','acceptance decision','finding disposition']),
],
'D3.9':[
('Multi-agent or multi-step workflows are tested for hand-off, delegation and shared-state failure modes.',['workflow test plan','handoff tests']),
('Context, permissions and instructions transferred between agents are validated for integrity and scope.',['context/permission transfer tests']),
('Coordination failures, contradictory actions and uncontrolled delegation are tested.',['coordination scenarios','delegation controls']),
('Potential emergent behaviours are monitored and have a defined escalation/intervention path.',['emergent-risk scenarios','intervention plan']),
],
'D3.10':[
('Initial deployment is deliberately limited in population, capability, environment or transaction scope to contain unknown failure.',['rollout plan','initial scope']),
('Defined criteria determine when the agent may expand to a larger scope or higher autonomy.',['promotion criteria','expansion gate']),
('Monitoring evidence is reviewed during each expansion stage.',['stage-gate review','monitoring results']),
('The deployment can be paused, rolled back or otherwise contained when material issues emerge.',['rollback / stop mechanism','rollback test']),
],
'D3.11':[
('Production operation is continuously or appropriately monitored against defined risk and performance indicators.',['monitoring specification','runtime telemetry']),
('Real-time or near-real-time intervention mechanisms exist for material harmful or unauthorised behaviour.',['kill switch / intervention control','intervention test']),
('Intervention thresholds and responsible responders are defined.',['alert thresholds','on-call / response matrix']),
('Interventions and material monitoring findings are retained for assurance and review.',['incident/intervention log','review record']),
],
'D3.12':[
('Expected behaviour and relevant operational baselines are defined for the deployed agent.',['behaviour baseline','monitoring thresholds']),
('Material deviations, anomalous tool use or unusual action patterns are detected.',['anomaly detection rules','anomaly alerts']),
('Detected anomalies trigger a defined response, investigation or escalation.',['anomaly response play','case records']),
],
'D3.13':[
('The organisation defines the monitoring objectives and the material events that must be logged.',['logging specification','monitoring objectives']),
('Material agent decisions, tool calls, approvals, errors and interventions are captured with attribution.',['event log schema','agent/tool/approval logs']),
('Logs preserve integrity and the context required to reconstruct material actions.',['log integrity controls','correlation identifiers']),
('Retention, access and privacy requirements for logs are defined and enforced.',['retention schedule','log access policy']),
],
'D3.14':[
('Logs and traces are actively monitored against defined alert conditions.',['log monitoring configuration','alert rules']),
('Alerts identify the material event, affected agent/resource and severity needed for triage.',['alert payload','severity model']),
('Alerts are routed to responsible roles with defined response expectations.',['routing configuration','on-call matrix']),
('Alert handling, escalation and closure are traceable.',['alert case records','closure log']),
],
'D3.15':[
('Material incidents involving agent behaviour are reviewed for root cause, control failure and impact.',['incident review','root-cause analysis']),
('Periodic assurance or audit checks the continuing fitness of agent controls and behaviour after deployment.',['periodic audit plan','assurance report']),
('Findings from incidents and audits feed into control, testing or deployment changes.',['finding register','retest/change record']),
],
'D3.16':[
('The organisation maintains a mechanism for identifying previously unknown or emergent agent risks.',['emergent-risk intake','risk monitoring']),
('Containment or intervention can be activated when an emergent risk is detected.',['containment mechanism','intervention procedure']),
('Escalation authority and decision ownership for emergent risks are predefined.',['escalation matrix','risk owner assignment']),
('Lessons from emergent risks are fed back into risk assessment, design controls and testing.',['lessons-learned record','control/test update']),
],
'D4.1':[
('Users interacting with an agent are clearly informed that they are interacting with an AI agent where disclosure is relevant.',['user disclosure','interface notice']),
('Users receive information about the agent’s capabilities, scope and material limitations.',['capability/limitation disclosure','user guidance']),
('Material agent actions, uncertainty or approval boundaries are presented in a way that supports responsible user judgement.',['action/decision disclosure','user interaction design']),
],
'D4.2':[
('Organisations or users integrating an agent receive relevant information about capabilities, limits and operating conditions.',['integrator documentation','capability profile']),
('Interfaces, dependencies, access assumptions and control boundaries are documented for integrators.',['integration specification','dependency documentation']),
('Material changes to capabilities, interfaces or limits are communicated to affected integrators.',['change notice','version/update record']),
],
'D4.3':[
('Oversight responsibilities are translated into role-specific training or competency requirements.',['role-based training requirement','competency matrix']),
('Training covers agent capabilities, limitations, failure modes and the human decisions required for meaningful oversight.',['training curriculum','oversight exercises']),
('Training is completed before a person assumes the relevant oversight authority.',['training completion record','role start record']),
('Competence is refreshed or reassessed when risks, agent capabilities or responsibilities materially change.',['refresh/reassessment cadence','competency assessment']),
],
'D4.4':[
('The operating model preserves the human knowledge and skills required to review, challenge and take over agent work.',['tradecraft requirements','role competency profile']),
('A practical fallback or manual operating path remains available for material tasks.',['manual fallback procedure','fallback test']),
('Automation design does not make human intervention impracticable or cause critical skills to atrophy without mitigation.',['tradecraft risk assessment','intervention/fallback exercise']),
],
'D4.5':[
('End users have practical mechanisms to challenge, test, report or escalate problematic agent behaviour within their role.',['user challenge mechanism','red-team/reporting procedure']),
('User-reported failures and assurance findings are captured and linked to the affected agent/version where possible.',['feedback register','issue linkage']),
('Real-world user feedback is included in periodic assurance, testing or control review.',['assurance sampling plan','feedback review record']),
('Material user findings are escalated and dispositioned through the governed risk process.',['finding / escalation record','disposition decision']),
],
}

with contract_p.open() as f: cdoc=yaml.safe_load(f)
with registry_p.open() as f: rdoc=yaml.safe_load(f)

# Update contracts: preserve control-level metadata; replace elements.
for c in cdoc['controls']:
    cid=c['control_id']
    if cid not in E: raise KeyError(cid)
    c['elements']=[{'id':f'e{i+1}','text':txt,'scope':'model'} for i,(txt,_) in enumerate(E[cid])]
    c['expected_evidence']=sorted({ev for _,evs in E[cid] for ev in evs})

# Update semantic registry only for MGF controls.
for c in rdoc['controls']:
    if c.get('framework')!='MGF Agentic':
        continue
    cid=c['control_id']
    old_by_id={e['id']:e for e in c.get('elements',[])}
    proto=copy.deepcopy(old_by_id.get('e1') or {})
    new=[]
    for i,(txt,evs) in enumerate(E[cid],1):
        eid=f'e{i}'
        old=copy.deepcopy(old_by_id.get(eid) or proto)
        # Use old source material as provenance for the refined semantic record.
        old['id']=eid
        old['governed_text']=txt
        old['intent']=txt
        old['scope']='model'
        old['applies_when']=None
        old['verification']='HUMAN_JUDGEMENT'
        old['verification_reason']='Source-grounded semantic element; no deterministic predicate is claimed unless separately specified.'
        old['expected_evidence']=evs
        old['audit_revised_elements']=None
        old['predicate_spec']={'present':False,'element_predicates':[],'applicability':None}
        old['locator']=f'controls.{cid}.elements[{i-1}]'
        # Preserve the existing source_basis on every split element as candidate provenance.
        old['source_grounding']='INSTRUMENT_MATCH_CANDIDATE'
        new.append(old)
    c['elements']=new
    c['semantic_status']='SEMANTIC_COVERED'

# Update framework summary counts from actual registry.
counts={}
for c in rdoc['controls']:
    fw=c.get('framework')
    counts[fw]=counts.get(fw,0)+len(c.get('elements',[]))
rdoc['summary']['framework_elements']={k:counts[k] for k in sorted(counts)}
# global semantic count
rdoc['summary']['semantic_elements']=sum(len(c.get('elements',[])) for c in rdoc['controls'])
rdoc['summary']['controls']=len(rdoc['controls'])
# Keep verification-mode summary honest from actual records.
from collections import Counter
vc=Counter(e.get('verification') for c in rdoc['controls'] for e in c.get('elements',[]))
rdoc['summary']['deterministic_elements']=vc.get('DETERMINISTIC',0)
rdoc['summary']['human_judgement_elements']=vc.get('HUMAN_JUDGEMENT',0)
rdoc['summary']['out_of_band_elements']=vc.get('OUT_OF_BAND',0)

# Write deterministically.
for path,doc in [(contract_p,cdoc),(registry_p,rdoc)]:
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=160), encoding='utf-8')

for p in [contract_p,registry_p]:
    h=hashlib.sha256(p.read_bytes()).hexdigest()
    out=p.with_suffix('.sha256')
    # existing convention for semantic is filename; preserve that
    out.write_text(f'{h}  {p.name}\n',encoding='utf-8')
    print(p.name, h)
print('MGF element counts:')
for c in cdoc['controls']:
    print(c['control_id'],len(c['elements']))
