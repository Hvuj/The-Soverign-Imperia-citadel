"""Predictive Task Sequencer — group blueprints so the same model stays resident, minimizing swaps
(the analog of the pasted plan's PCIe-thrashing fix). Pure and deterministic."""

from collections.abc import Callable, Iterable

from citadel.services.execute.blueprint import Blueprint


def sequence(
    blueprints: Iterable[Blueprint],
    key: Callable[[Blueprint], str] | None = None,
) -> list[list[Blueprint]]:
    key = key or (lambda bp: bp.assigned_tier)
    groups: dict[str, list[Blueprint]] = {}
    order: list[str] = []
    for blueprint in blueprints:
        group_key = key(blueprint)
        if group_key not in groups:
            groups[group_key] = []
            order.append(group_key)
        groups[group_key].append(blueprint)
    return [groups[k] for k in order]
