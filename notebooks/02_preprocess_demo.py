# %% [markdown]
# # 02 — Preprocess Demo
#
# Walks through the four preprocessing steps described in §3.3 of the paper:
# illegal-character removal, tokenization, stopword removal, and
# single-character drop. Plus lemmatization for the final form used in
# co-occurrence counting.

# %%
import sys
sys.path.insert(0, '..')

from services.mining.text_processing import preprocess_text
from services.mining.cooccurrence import accumulate_tokens
from collections import Counter

# %% [markdown]
# ## A sample xDD snippet
#
# A real snippet from xDD describing a porphyry deposit. Note the
# characteristic features: compound terms, element symbols, mixed
# punctuation, scientific abbreviations.

# %%
sample_snippet = (
    "The Bingham Canyon porphyry Cu-Mo deposit is hosted by a "
    "quartz-monzonite stock of late Eocene age (38.6 Ma). Hydrothermal "
    "alteration includes potassic (biotite+K-feldspar) and propylitic "
    "(chlorite+epidote+calcite) assemblages, with sulfide mineralization "
    "(chalcopyrite, molybdenite, pyrite) concentrated in quartz veins."
)
print(sample_snippet)

# %% [markdown]
# ## Step 1+2+3+4: preprocess_text() applies all four steps

# %%
processed = preprocess_text(sample_snippet)
print(processed)

# %% [markdown]
# Note what's gone:
# - Punctuation stripped
# - Stopwords removed ("the", "is", "of", "with", etc.)
# - Single-character tokens dropped (the element symbol "K" in "K-feldspar" is lost; this is the known limitation discussed in §3.3 and §5)

# %% [markdown]
# ## Step 5: lemmatize and count

# %%
counts = Counter()
n_added = accumulate_tokens(processed, counts)
print(f"Added {n_added} tokens")
print(f"\nTop 10 tokens by count:")
for word, n in counts.most_common(10):
    print(f"  {n:3d}  {word}")

# %% [markdown]
# Observe:
# - `deposit`, `mineralization` are lemma forms (not "deposits", "mineralized")
# - Geological terminology survives: `porphyry`, `cu-mo`, `quartz`, `monzonite`, `chalcopyrite`, `molybdenite`, `pyrite`
# - Multi-snippet mining would accumulate this Counter across thousands of snippets

# %% [markdown]
# ## What's lost
#
# The single-character drop step removes individual element symbols. This
# is the known cost discussed in §3.3 of the paper. If you needed to
# preserve U, K, Pb, etc. for isotope work, modify `preprocess_text()` to
# skip the single-character filter, or pre-detect these symbols with a
# regex before tokenization.
