# %% [markdown]
# # 04 — In-Stream Counter Pruning (Strategy A)
#
# Demonstrates the in-stream pruning step discussed in §5 of the paper.
# Without pruning, very high-frequency seed terms (those with >5M unique
# partner tokens) exceed the 1 GiB pod memory budget during streaming and
# OOM-kill the worker before the mine completes.
#
# Strategy A: every 500K snippets, if the Counter has grown past 5M
# unique tokens, drop entries with count below 5. Pruned tokens have
# near-zero PMI by construction and would not appear in the top-N ranking.

# %%
import sys
sys.path.insert(0, '..')

from collections import Counter
from services.mining.cooccurrence import maybe_prune_counter
import random

# %% [markdown]
# ## Simulated mega-frequency term
#
# We build a Counter that mimics the partner-token distribution for a
# very common term. Most partners are noise (count=1 or 2); a small
# population are real associations (count >> 5).

# %%
random.seed(42)

counts = Counter()

# Generate ~6M unique low-count tokens (noise)
print("Building synthetic noise vocabulary (this takes ~10 sec)...")
for i in range(6_000_000):
    counts[f"noise_token_{i}"] = random.choice([1, 1, 1, 1, 2, 2, 3])

# Sprinkle in 5,000 high-signal tokens with counts that would survive PMI ranking
for i in range(5_000):
    counts[f"signal_token_{i}"] = random.randint(20, 5000)

print(f"\nPre-prune Counter size: {len(counts):,} unique tokens")
print(f"Estimated memory (at 250 bytes/entry): {len(counts) * 250 / 1024**2:.0f} MiB")

# %% [markdown]
# A 6M-entry Counter at ~250 bytes per entry occupies roughly 1.4 GiB —
# enough to OOM a 1 GiB pod. Now apply pruning.

# %%
result = maybe_prune_counter(
    counts,
    n_snippets=500_000,
    trigger_size=5_000_000,
    keep_min=5,
)
print(f"\nPrune result: {result}")
print(f"Post-prune Counter size: {len(counts):,} unique tokens")
print(f"Estimated memory: {len(counts) * 250 / 1024**2:.0f} MiB")

# %% [markdown]
# All 5,000 signal tokens are preserved (they had counts well above the
# keep_min=5 threshold). The 6M noise tokens are dropped because they
# would never appear in the top-N partner ranking.
#
# Verify that signal is intact:

# %%
n_signal_remaining = sum(1 for k in counts if k.startswith("signal_token_"))
n_noise_remaining = sum(1 for k in counts if k.startswith("noise_token_"))
print(f"Signal tokens remaining: {n_signal_remaining} / 5,000")
print(f"Noise tokens remaining:  {n_noise_remaining:,} / 6,000,000")

# %% [markdown]
# ## The trade-off
#
# Pruning is lossless with respect to the published top-N PMI rankings:
# pruned tokens cannot influence the top-N because their counts are
# already below threshold. The trade-off is for downstream uses that
# need to inspect the long tail of low-frequency partners — those
# entries are unrecoverable for this mine.
#
# Tune the thresholds in `services/mining_config.py`:
#
# - `SNAPSHOT_PRUNE_CHECK_INTERVAL` — how often to check (every N snippets)
# - `SNAPSHOT_PRUNE_TRIGGER_SIZE` — when to prune (vocab size threshold)
# - `SNAPSHOT_PRUNE_KEEP_MIN` — minimum count to retain
#
# On hardware with more memory, raise the trigger size or lower the
# keep_min to preserve more tail vocabulary. On tighter memory budgets,
# lower the trigger size or raise the keep_min for more aggressive pruning.
