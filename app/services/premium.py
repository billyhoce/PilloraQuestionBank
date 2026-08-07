"""Who may open which premium paper.

Premium is sold per school level, so the question is never "is this user
premium" but "does this user hold *this paper's* school level". A paper's school
level is the one on its ``level`` — a paper also reaches a school level through
its ``stream``, but only ``level`` is authoritative here, and paper writes reject
the two disagreeing (``app/services/paper_admin.py``).

Entitlement is derived from ``user_premium_school_level`` rather than stored on
``User.role``, so a user's tier can never disagree with what they can open.
Admins are unrestricted.

The gate comes in two shapes because it is needed on both sides of the database
boundary: :func:`can_view_paper` for a loaded ``Paper``, and
:func:`restrict_premium_pool` to keep unaffordable papers out of a query before
it runs. They must agree — change one, change the other.
"""

from typing import Callable, Optional

from sqlalchemy import or_

from app.models.orm import Level, Paper, User

# Decides whether a viewer may see a given paper's images. Passed around rather
# than imported so serializers cross the same seam as the presigner does.
PremiumGate = Callable[[Paper], bool]


def entitled_school_level_ids(user: Optional[User]) -> Optional[set[int]]:
    """School level ids ``user`` has premium access to.

    ``None`` means unrestricted (admin); an empty set means no premium access at
    all, which is also what an anonymous viewer gets.
    """
    if user is None:
        return set()
    if user.role == "admin":
        return None
    return {sl.id for sl in user.premium_school_levels}


def premium_gate(user: Optional[User]) -> PremiumGate:
    """A :data:`PremiumGate` bound to ``user``.

    Resolving the entitlements once and closing over them keeps serializing a
    page of results from re-reading them per row.
    """
    entitled = entitled_school_level_ids(user)

    def gate(paper: Paper) -> bool:
        if not paper.is_premium:
            return True
        return entitled is None or paper.level.school_level_id in entitled

    return gate


def can_view_paper(user: Optional[User], paper: Paper) -> bool:
    """Whether ``user`` may see ``paper``'s images and generate from it."""
    return premium_gate(user)(paper)


def restrict_premium_pool(query, user: Optional[User]):
    """Drop papers ``user`` cannot generate from out of a question query.

    The query must already join ``Level`` (generation's candidate pool does).
    Unlike the browse endpoints — which still return locked questions as
    metadata-only teasers — generation has no use for a paper the user cannot
    render, so these leave the pool entirely.
    """
    entitled = entitled_school_level_ids(user)
    if entitled is None:
        return query
    if not entitled:
        return query.filter(Paper.is_premium.is_(False))
    return query.filter(
        or_(Paper.is_premium.is_(False), Level.school_level_id.in_(entitled))
    )
