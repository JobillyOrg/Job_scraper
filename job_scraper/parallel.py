from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


def map_pool(fn: Callable[[T], R], items: Iterable[T], max_workers: int = 12) -> list[R]:
    seq = list(items)
    if not seq:
        return []
    if len(seq) == 1:
        return [fn(seq[0])]
    workers = max(1, min(max_workers, len(seq)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, seq))


def gather(fns: Iterable[Callable[[], list]], max_workers: int = 3) -> list:
    jobs: list = []
    seq = list(fns)
    if not seq:
        return jobs
    if len(seq) == 1:
        try:
            return list(seq[0]() or [])
        except Exception:
            logger.exception("Search task failed")
            return []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(seq))) as pool:
        futures = [pool.submit(fn) for fn in seq]
        for future in as_completed(futures):
            try:
                jobs.extend(future.result() or [])
            except Exception:
                logger.exception("Search task failed")
    return jobs
