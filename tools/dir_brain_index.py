from _brain_common import ROOT, write_json

out=ROOT/'.claude/state/directory-brain-index.json'; write_json(out, {'directories': []}); print(f'wrote {out}')
