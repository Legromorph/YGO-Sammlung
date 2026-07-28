from __future__ import annotations

from datetime import timedelta
import unittest

from app.models import SyncJob
from app.services.sync import (
    _build_job_lock_key,
    _job_health,
    _merge_price_job_payload,
    _price_targets_overlap,
)
from app.time_utils import utc_now


class PriceJobTests(unittest.TestCase):
    def test_price_jobs_share_one_provider_lock(self) -> None:
        self.assertEqual(
            _build_job_lock_key("price_update", {"inventory_item_ids": [1]}),
            _build_job_lock_key("price_update", {"inventory_item_ids": [2]}),
        )

    def test_overlapping_job_payloads_merge_targets_without_losing_ids(self) -> None:
        merged = _merge_price_job_payload(
            {"inventory_item_ids": [1, 3], "card_print_ids": [7], "trigger": "scheduler"},
            {"inventory_item_ids": [1, 2], "card_print_ids": [8], "trigger": "manual"},
        )
        self.assertEqual(merged["inventory_item_ids"], [1, 2, 3])
        self.assertEqual(merged["card_print_ids"], [7, 8])
        self.assertEqual(merged["trigger"], "manual")

    def test_price_target_overlap_distinguishes_unrelated_batches(self) -> None:
        self.assertTrue(
            _price_targets_overlap(
                {"inventory_item_ids": [1, 2]},
                {"inventory_item_ids": [2, 3]},
            )
        )
        self.assertFalse(
            _price_targets_overlap(
                {"inventory_item_ids": [1]},
                {"inventory_item_ids": [2]},
            )
        )

    def test_stale_running_job_uses_aware_utc_timestamps(self) -> None:
        now = utc_now()
        job = SyncJob(
            job_type="price_update",
            lock_key="price_update:global",
            status="running",
            created_at=now - timedelta(hours=1),
            started_at=now - timedelta(hours=1),
        )

        is_stuck, reason = _job_health(job, now=now)

        self.assertTrue(is_stuck)
        self.assertIn("running", reason or "")

    def test_claim_index_and_running_lock_index_are_declared(self) -> None:
        index_names = {index.name for index in SyncJob.__table__.indexes}
        self.assertIn("ix_sync_jobs_claim", index_names)
        self.assertIn("uq_sync_jobs_running_lock_key", index_names)


if __name__ == "__main__":
    unittest.main()
