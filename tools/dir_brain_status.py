from _brain_common import ROOT, load_json

d=load_json(ROOT/'.claude/state/directory-brain-index.json', {'directories': []}); print(f"directory brain entries: {len(d.get('directories', []))}")
