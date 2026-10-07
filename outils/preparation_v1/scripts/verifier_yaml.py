#!/usr/bin/env python3
from pathlib import Path
import yaml
root=Path(__file__).resolve().parents[1]
for app in ('vir','pgdr','cpl'):
    d=yaml.safe_load((root/'config'/f'{app}_cbs_requirements.yaml').read_text())
    assert d['schema_authority']=='application_integration_draft'
    assert d['application']==app.upper() and d['entry_mode']=='source'
    ids=[x['id'] for x in d['requirements']]
    assert len(ids)==len(set(ids))
    for r in d['requirements']:
        assert r['required_result'] and r['constraints'] and r['evidence_refs']
r=yaml.safe_load((root/'config/runtime.yaml').read_text())
assert all(not p['enabled'] for p in r['providers'].values())
assert r['v1']['model_role']=='order_only'
print('3 déclarations source et configuration V1 valides ; aucune admission CBS revendiquée.')
