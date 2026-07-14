"""Generate service — question selection for paper generation.

Selection is driven by a target (a marks total or a question count) and an
algorithm (random or in-order):

- ``knapsack_select`` picks a randomized subset of questions whose marks sum as
  close as possible to a target. It is a randomized-restart greedy rather than an
  exact optimizer: at v1 scale a simple iterative approach is fine, and the
  randomness is a feature — the same filters/target produce a *different* paper
  each time, while exact-match totals are still reliably found across restarts.
- ``in_order_select`` is the deterministic marks counterpart: a single greedy
  pass over the pool in its given (id) order that stops just before exceeding the
  target, so identical filters/target always yield the same questions.
- ``count_select`` selects a fixed *number* of questions, either the first N (in
  order) or N at random.
"""
import random

# Restart budget. Scales with pool size so larger pools still explore enough
# orderings, but stays bounded for responsiveness at v1 scale.
_MIN_RESTARTS = 200
_MAX_RESTARTS = 2000
_RESTARTS_PER_QUESTION = 20


def _restart_count(pool_size: int) -> int:
    return max(_MIN_RESTARTS, min(_MAX_RESTARTS, pool_size * _RESTARTS_PER_QUESTION))


def knapsack_select(questions: list, target_marks: int) -> list:
    """Select a subset of ``questions`` whose marks sum near ``target_marks``.

    Prefers an exact match; otherwise returns the subset whose total is closest
    to the target, allowing a slight overshoot if it lands closer. Questions
    with null or non-positive marks are ignored. Returns ``[]`` for a
    non-positive target or when nothing is selectable.
    """
    if target_marks <= 0:
        return []

    pool = [q for q in questions if q.marks is not None and q.marks > 0]
    if not pool:
        return []

    best_subset: list = []
    best_distance = target_marks  # distance of the empty subset (sum 0)
    ties_seen = 1  # the empty subset is the initial best; reservoir counter

    def consider(subset: list, total: int) -> None:
        nonlocal best_subset, best_distance, ties_seen
        distance = abs(total - target_marks)
        if distance < best_distance:
            best_subset = list(subset)
            best_distance = distance
            ties_seen = 1
        elif distance == best_distance:
            # Reservoir sampling over equally-good subsets so repeated calls
            # return different papers instead of always the first found.
            ties_seen += 1
            if random.random() < 1.0 / ties_seen:
                best_subset = list(subset)

    for _ in range(_restart_count(len(pool))):
        random.shuffle(pool)
        subset: list = []
        total = 0
        for q in pool:
            if total >= target_marks:
                break
            if subset:
                # The subset before adding this question stays under the target;
                # consider it, as it may be the closest under-total.
                consider(subset, total)
            subset.append(q)
            total += q.marks
        consider(subset, total)
        if best_distance == 0:
            break

    return best_subset


def in_order_select(questions: list, target_marks: int) -> list:
    """Deterministically pick questions from the top until adding the next would
    exceed ``target_marks``.

    A single greedy pass over the pool in its given order (the caller supplies it
    ordered by ``Question.id``): accumulate from the top, adding each question
    while it still fits, and **stop at the first question that would push the
    total over the target** — the result never overshoots. No shuffling,
    restarts, or tie-break randomness, so the same filtered pool and target
    always return the same questions. Questions with null or non-positive marks
    are ignored. Returns ``[]`` for a non-positive target or when nothing is
    selectable.
    """
    if target_marks <= 0:
        return []

    pool = [q for q in questions if q.marks is not None and q.marks > 0]

    selected: list = []
    total = 0
    for q in pool:
        if total + q.marks > target_marks:
            break
        selected.append(q)
        total += q.marks

    return selected


def count_select(questions: list, count: int, *, randomize: bool) -> list:
    """Select ``count`` questions by number (not by marks).

    With ``randomize`` picks ``count`` questions uniformly at random; otherwise
    takes the first ``count`` in the pool's given order (id order). Unlike the
    marks-based selectors this does **not** filter out null-mark questions — the
    caller is choosing a fixed number of questions regardless of marks. Returns
    ``[]`` for a non-positive ``count`` or an empty pool; if ``count`` exceeds the
    pool size, returns the whole pool.
    """
    if count <= 0:
        return []

    pool = list(questions)
    if not pool:
        return []

    if randomize:
        return random.sample(pool, min(count, len(pool)))
    return pool[:count]
