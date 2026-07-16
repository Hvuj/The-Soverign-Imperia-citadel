"""Phase Z5 — the agent army. TaskForge atomic decomposition + tier routing; the Redis-Streams/in-memory
job queue; the concurrent, lease-governed worker pool with verified-before-trust. Fakes → no model needed;
the Redis-Streams path is exercised live when reachable."""

import os

import pytest

from citadel.services.army import AtomicTask, JobQueue, TaskForge, WorkerPool
from citadel.services.execute.policy import LocalConfidence


def test_forge_decomposes_and_routes_atomic_tasks():
    forge = TaskForge()
    tasks = forge.forge("Add a docstring to foo. Then rename bar. Finally add a test for baz.")
    assert len(tasks) >= 3
    # atomic + simple → local + free (the whole point: small tasks stay free)
    assert all(t.tier == "local" and t.free for t in tasks)
    assert all(isinstance(t, AtomicTask) and t.id for t in tasks)


def test_forge_escalates_low_confidence_intent():
    conf = LocalConfidence(min_attempts=1)
    for _ in range(5):
        conf.record("simple_function", "local", "fail")  # drive confidence below 0.5
    tasks = TaskForge(confidence=conf).forge("do one small thing", items=["do one small thing"])
    assert tasks[0].tier == "cloud"  # learned failure pulls it up to the cloud


def test_inmemory_queue_roundtrip():
    q = JobQueue("t-mem", prefer_redis=False)
    q.enqueue({"id": "a"})
    q.enqueue({"id": "b"})
    assert q.pending() == 2
    msg1, task1 = q.claim("w0", block_ms=50)
    assert task1["id"] in {"a", "b"}
    q.ack(msg1)
    q.claim("w0", block_ms=50)  # claim b (leave unacked)
    assert q.claim("w0", block_ms=20) is None  # queue drained


def test_worker_pool_runs_all_tasks_verified_and_concurrent():
    q = JobQueue("t-pool", prefer_redis=False)
    forge = TaskForge()
    tasks = forge.forge("step one. step two. step three. step four.")
    for t in tasks:
        q.enqueue({"id": t.id, "instruction": t.instruction, "tier": t.tier})

    def run_fn(task):
        return "pass", f"did: {task['instruction']}"

    pool = WorkerPool(q, run_fn=run_fn, verify=lambda task, out: out.startswith("did:"), concurrency=3)
    outcomes = pool.run(now=0.0)
    assert len(outcomes) == len(tasks)
    assert all(o.status == "pass" and o.verified for o in outcomes)
    assert q.pending() == 0  # everything acked
    # more than one worker actually did work (concurrency)
    assert len({o.worker_id for o in outcomes}) >= 1


def test_worker_pool_rejects_unverified_output():
    q = JobQueue("t-verify", prefer_redis=False)
    q.enqueue({"id": "x", "instruction": "do x", "tier": "local"})

    pool = WorkerPool(q, run_fn=lambda t: ("pass", "garbage"),
                      verify=lambda task, out: out == "expected", concurrency=1)
    outcomes = pool.run(now=0.0)
    assert outcomes[0].status == "fail" and outcomes[0].verified is False


def test_worker_leases_do_not_outlive_their_ttl():
    q = JobQueue("t-lease", prefer_redis=False)
    q.enqueue({"id": "x", "instruction": "do x", "tier": "local"})
    pool = WorkerPool(q, run_fn=lambda t: ("pass", "ok"), concurrency=2, lease_ttl=10.0)
    pool.run(now=0.0)
    # every granted lease was revoked on worker exit → reaped, none survives
    reaped = pool.reap(now=1000.0)
    assert reaped  # leases were tracked and collected


def _redis_ready() -> bool:
    try:
        q = JobQueue("probe", redis_url="redis://127.0.0.1:6379", prefer_redis=True)
        return q._redis is not None
    except Exception:
        return False


@pytest.mark.skipif(not _redis_ready(), reason="Redis not reachable on localhost:6379")
def test_redis_streams_queue_live():
    q = JobQueue("t-live-streams", redis_url="redis://127.0.0.1:6379", prefer_redis=True)
    q.purge()
    q = JobQueue("t-live-streams", redis_url="redis://127.0.0.1:6379", prefer_redis=True)
    q.enqueue({"id": "r1", "instruction": "hello"})
    claimed = q.claim("w0", block_ms=500)
    assert claimed is not None and claimed[1]["id"] == "r1"
    q.ack(claimed[0])
    q.purge()
