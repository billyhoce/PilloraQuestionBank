"""``unrouted``: the one task of a section no extractor can take.

Records, as ``skipped`` with its reason, a section ``ingester.router`` would not
route (an answer section with no template). It exists so such a section appears in
the job instead of vanishing.
"""

from __future__ import annotations

import logging

from ingester.router import choose_route

from ..outcome import Outcome, StageContext, skipped
from ..registry import CPU, SECTION, UNROUTED, Stage
from ..sections import load_section

log = logging.getLogger(__name__)


def run(ctx: StageContext) -> Outcome:
    section = load_section(ctx)
    route = choose_route(section)
    if route.needs_review:
        log.warning("%s: not routed: %s", ctx.section, route.reason)
    return skipped(route.reason, needs_review=route.needs_review or section.segment.needs_review)


STAGE = Stage(name="unrouted", scope=SECTION, kind=CPU, run=run, route=UNROUTED)
