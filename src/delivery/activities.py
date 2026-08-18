"""Activities: the non-deterministic work a workflow delegates to the worker.

For now this is a single trivial activity that proves the wiring. PR 2 replaces
it with the real order steps (charge, restaurant, prepare, dispatch, delivery).
"""

from temporalio import activity


@activity.defn
async def say_hello(name: str) -> str:
    return f"Hello, {name}!"
