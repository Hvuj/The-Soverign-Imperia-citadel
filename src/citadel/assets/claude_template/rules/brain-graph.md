# Brain graph rules

The graph is a routing/index layer.

Files:
- `docs/brain/nodes/**/*.md`: source nodes
- `docs/brain/graph-index.md`: small routing index
- `docs/brain/graph.json`: generated data
- `docs/brain/graph.html`: visual UI only

Token rules:
- do not load graph HTML into agent context
- do not load full graph JSON unless debugging graph generation
- read max 1-3 nodes initially
- follow max one-hop links unless deep mode
- keep nodes short
