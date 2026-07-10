#!/usr/bin/env python3

import argparse
import json

# The Citadel ships workspace-agnostic: no domain/framework vocabulary is hardcoded. Domain
# specialists and their trigger keywords are LEARNED per workspace (see the per-province learning
# design) and would be loaded from workspace config here, not shipped. Empty by default.
DOMAIN_RULES: dict[str, list[str]] = {}


def classify(text: str):
    t = text.lower()
    results = []
    for agent, keywords in DOMAIN_RULES.items():
        hits = [kw for kw in keywords if kw in t]
        if hits:
            budget = 'standard' if len(hits) >= 2 else 'micro'
            if any(x in t for x in ['critical','deep','production','e2e','regression','failed again']):
                budget = 'deep'
            results.append({'agent': agent, 'budget': budget, 'hits': hits[:8]})
    if not results:
        results.append({'agent':'technical-domain-router','budget':'micro','hits':[]})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('text', nargs='*')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    text = ' '.join(args.text).strip() or input('Task or changed files: ').strip()
    results = classify(text)
    if args.json:
        print(json.dumps({'text':text,'routing':results}, indent=2))
        return
    print('# Technical Domain Routing')
    for item in results:
        print(f"- {item['agent']}: {item['budget']} mode")
        if item['hits']:
            print('  hits: ' + ', '.join(item['hits']))


if __name__ == '__main__':
    main()
