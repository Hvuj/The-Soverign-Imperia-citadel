#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict, deque

from _brain_common import CONFIG, ROOT, SEARCH_STATE, load_json, tokenize


def ensure():
    if not (SEARCH_STATE / "index.json").exists(): subprocess.run([sys.executable, "tools/build_brain_search_index.py", "--quiet"], cwd=ROOT)


def apply_skip_rules(agents, it, cfg, top_direct_topics=None):
    rules = cfg.get("agent_skip_rules", {})
    out = []
    for a in agents:
        rule = rules.get(a)
        if rule:
            if it in rule.get("skip_when_intent", []):
                continue
            explicit = rule.get("skip_unless_explicit_topic", [])
            if explicit and top_direct_topics is not None:
                if not any(f"topic:{t}" in top_direct_topics for t in explicit):
                    continue
        out.append(a)
    return out


def uniq(xs):
    out=[]; seen=set()
    for x in xs:
        if x and x not in seen: out.append(x); seen.add(x)
    return out


def intent(q):
    t=q.lower()
    if any(x in t for x in ["fix","error","failed","traceback","bug"]): return "debugging"
    if any(x in t for x in ["add","change","implement","build","refactor"]): return "implementation"
    if any(x in t for x in ["test","validate","verify","check"]): return "validation"
    if any(x in t for x in ["docs","documentation","learn this"]): return "docs_ingestion"
    if re.search(r'\b(bi|metric|kpi)\b', t): return "bi"
    return "question"


def _unit_boost(scores, unit, cfg):
    """Boost scores for nodes belonging to the active unit's domain."""
    if not unit or unit == "core":
        return
    unit_agents = cfg.get("unit_to_agents", {}).get(unit, [])
    unit_skills = cfg.get("unit_to_skills", {}).get(unit, [])
    for nid in list(scores.keys()):
        if nid.startswith("agent:") and nid.replace("agent:", "") in unit_agents:
            scores[nid] = scores.get(nid, 0) + 4
        if nid.startswith("topic:"):
            topic = nid.replace("topic:", "")
            domain_agents = cfg.get("domain_to_agents", {}).get(topic, [])
            if any(a in unit_agents for a in domain_agents):
                scores[nid] = scores.get(nid, 0) + 2


def search(query, depth=None, limit=None, unit=None):
    ensure(); cfg=load_json(CONFIG,{}); it=intent(query); depth=depth if depth is not None else int(cfg.get("depth_by_intent",{}).get(it,cfg.get("default_depth",2))); limit=limit or int(cfg.get("max_context_nodes",12))
    if unit is None:
        try:
            import json as _json

            from _brain_common import STATE as _STATE
            _task = _STATE/"current-task.json"
            if _task.exists(): unit = _json.loads(_task.read_text()).get("unit","core")
        except Exception: unit = "core"
    idx=load_json(SEARCH_STATE/"index.json",{"nodes":{}}); nodes=idx.get("nodes",{})
    kw=load_json(SEARCH_STATE/"keyword-to-nodes.json",{}); alias=load_json(SEARCH_STATE/"alias-to-nodes.json",{}); neigh=load_json(SEARCH_STATE/"node-to-neighbors.json",{}); rank=load_json(SEARCH_STATE/"node-rank.json",{})
    scores=defaultdict(float); direct=defaultdict(float); toks=tokenize(query); low=query.lower()
    for tok in toks:
        for n in kw.get(tok,[]): scores[n]+=3; direct[n]+=3
        for n in alias.get(tok,[]): scores[n]+=5; direct[n]+=5
    for k, ids in alias.items():
        if k and re.search(r'(?<![a-z0-9])' + re.escape(k) + r'(?![a-z0-9])', low):
            for n in ids: scores[n]+=6; direct[n]+=6
    if not scores: scores["topic:graph-brain"]=1; direct["topic:graph-brain"]=1
    _unit_boost(scores, unit, cfg)
    max_direct=max(direct.values()) if direct else 0
    top_direct_topics={nid for nid,s in direct.items() if nid.startswith("topic:") and max_direct>0 and s>=max_direct*0.35}
    q=deque((n,0,s) for n,s in dict(scores).items()); seen=set(scores)
    while q:
        n,d,s=q.popleft()
        if d>=depth: continue
        for nb in neigh.get(n,[]):
            tid=nb["id"]; val=s*(0.55**(d+1))*max(1,float(nb.get("weight",1))); scores[tid]=max(scores.get(tid,0),val)
            if tid not in seen: seen.add(tid); q.append((tid,d+1,s))
    rows=[]
    for nid, score in scores.items():
        node=nodes.get(nid)
        if node: rows.append({"id":nid,"score":round(score+0.25*rank.get(nid,{}).get("base_rank",0),3),"node":node})
    rows=sorted(rows,key=lambda x:x["score"], reverse=True)[:limit]
    agents=[]; skills=[]; files=[]; n_agents=load_json(SEARCH_STATE/"node-to-agents.json",{}); n_skills=load_json(SEARCH_STATE/"node-to-skills.json",{})
    for r in rows:
        n=r["node"]; nid=r["id"]
        if n.get("type")=="topic":
            topic=n.get("topic") or nid.replace("topic:",""); agents+=cfg.get("domain_to_agents",{}).get(topic,[]); skills+=cfg.get("domain_to_skills",{}).get(topic,[])
        agents += n_agents.get(nid,[])
        skills += [x.replace("skill:","") for x in n_skills.get(nid,[])]
        if n.get("type")=="agent": agents.append(nid)
        if n.get("type")=="skill": skills.append(nid.replace("skill:",""))
        files += n.get("files",[])
    intent_cap=int(cfg.get("max_agents_by_intent",{}).get(it,cfg.get("max_agents",8))); hard_cap=int(cfg.get("max_agents",8)); agent_cap=min(hard_cap,intent_cap)
    agents=apply_skip_rules(uniq(agents), it, cfg, top_direct_topics)
    return {"query":query,"intent":it,"depth":depth,"selected_nodes":[{"id":r["id"],"score":r["score"],"title":r["node"].get("title"),"type":r["node"].get("type"),"path":r["node"].get("path"),"summary":r["node"].get("summary","")[:400]} for r in rows],"agents":agents[:agent_cap],"skills":uniq(skills)[:int(cfg.get("max_skills",8))],"files":uniq(files)[:int(cfg.get("max_files",20))],"memory_refs":[],"reasoning_needed":True}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("query",nargs="*"); ap.add_argument("--depth",type=int); ap.add_argument("--limit",type=int); ap.add_argument("--json",action="store_true"); args=ap.parse_args()
    res=search(" ".join(args.query).strip() or input("Query: "), args.depth, args.limit)
    if args.json: print(json.dumps(res,indent=2)); return
    print("# Brain Search"); print(f"intent: {res['intent']}"); print(f"depth: {res['depth']}"); print("\n## Nodes")
    for n in res["selected_nodes"]: print(f"- {n['id']} ({n['type']}) score={n['score']} {n['title']}")
    print("\n## Agents"); [print(f"- {a}") for a in res["agents"]]
    print("\n## Skills"); [print(f"- {s}") for s in res["skills"]]


if __name__=="__main__": main()
