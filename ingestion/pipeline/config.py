"""Tunable knobs for the stage runner. See pipeline/README.md."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

from ingester import IngestConfig
from question_extractor import ExtractConfig


@dataclass(frozen=True)
class PipelineConfig:
    # --- scheduling -------------------------------------------------------
    # How long a claimed task stays the claimant's without a heartbeat. A live
    # runner renews it every lease/3 (``heartbeat_seconds``), so the lease does
    # not have to outlast a stage -- a vision call or an OCR container may run for
    # minutes -- only two missed heartbeats (a stalled connection, a long GC
    # pause). A crashed runner's task is therefore handed back within two
    # minutes. A judgement, not a measurement: nothing here has been timed.
    lease_seconds: float = 120.0
    # How long ``run --watch`` (and a drain waiting on another runner's task)
    # sleeps when nothing is ready. Stages take seconds to minutes and the queue
    # holds a handful of jobs, so two seconds adds no visible latency and costs
    # one trivial query.
    poll_interval_seconds: float = 2.0
    # Attempts a task gets before a lease that keeps expiring marks it failed:
    # the first run plus two retries. A transient crash (container restart, an
    # out-of-memory kill under the VM's 6 GB) clears on a retry; a stage that
    # kills its runner every time would otherwise loop forever. A stage that
    # *reports* failure is never retried automatically.
    retry_limit: int = 3
    # ``pipeline retry`` starts a task's count again: the limit stops a stage that
    # kills its runner from looping on its own, and a person asking for another go
    # is the judgement it was waiting for.

    # --- what the stages themselves run with ------------------------------
    ingest: IngestConfig = field(default_factory=IngestConfig)
    extract: ExtractConfig = field(default_factory=ExtractConfig)

    @property
    def heartbeat_seconds(self) -> float:
        return self.lease_seconds / 3

    def stage_config_hash(self) -> str:
        """Hash of the settings that change what a stage writes.

        The scheduling knobs are left out: retuning the lease must not make every
        earlier job look as though it was produced by a different configuration.
        So is ``extract.ocr_command``: it says where Tesseract runs, not how it
        reads (the manifest's config snapshot leaves it out for the same reason),
        and a job moved to a host with a different command is the same job.
        """
        payload = json.dumps(
            {"ingest": asdict(self.ingest), "extract": self.extract_settings()}, sort_keys=True
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def extract_settings(self) -> dict:
        """``ExtractConfig`` as a plain dict, without ``ocr_command`` (see above)."""
        return {k: v for k, v in asdict(self.extract).items() if k != "ocr_command"}
