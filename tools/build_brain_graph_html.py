#!/usr/bin/env python3
from _brain_common import ROOT

out=ROOT/"docs/brain/graph.html"; out.write_text("<!doctype html><html><body><h1>Project Brain Graph</h1><script>fetch('graph.json').then(r=>r.json()).then(g=>document.body.append(JSON.stringify({nodes:g.nodes.length,links:g.links.length})))</script></body></html>"); print(f"wrote {out}")
