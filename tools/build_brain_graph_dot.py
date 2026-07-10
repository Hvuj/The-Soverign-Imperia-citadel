#!/usr/bin/env python3
from _brain_common import ROOT

out=ROOT/"docs/brain/graph.dot"; out.write_text("digraph Brain {\n}\n"); print(f"wrote {out}")
