"""Snippet text preprocessing for term mining.

Vendored from the MSc geonlp notebooks (`src/text_processing.py`) so the
mining worker produces output identical to what's already in the corpus.

Pipeline:
  remove_illegal_chars → lowercase → strip punctuation/numbers → drop
  stopwords (NLTK English + small geo-noise set) → drop single-char tokens.
"""

import re
import string
import unicodedata

import nltk
from nltk.corpus import stopwords


# Required NLTK resources. Downloaded once at Docker build time
# (see Dockerfile) so this module import is offline-safe.
_DEFAULT_STOPWORDS = None


def _stopwords() -> set:
    global _DEFAULT_STOPWORDS
    if _DEFAULT_STOPWORDS is None:
        sw = set(stopwords.words("english"))
        sw.update({"fig", "et", "al", "eg"})
        _DEFAULT_STOPWORDS = sw
    return _DEFAULT_STOPWORDS


def remove_illegal_chars(text: str) -> str:
    """Normalize Unicode, strip accents, drop non-ASCII and unsafe symbols."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\x00-\x7F]+", " ", text)
    illegal_chars = re.compile(r"[^\w\s.,;\'\"!?()\-]")
    text = illegal_chars.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def preprocess_text(text: str, stop_words: set | None = None) -> str:
    """Cleans and tokenizes a single snippet for downstream counting.

    - lower-case, ASCII-only
    - punctuation and numbers replaced with spaces
    - stopwords (NLTK English + {fig, et, al, eg}) dropped
    - single-character tokens dropped
    - whitespace collapsed

    Returns a single space-joined string of surviving tokens.
    """
    if stop_words is None:
        stop_words = _stopwords()
    if not isinstance(text, str):
        return ""

    text = remove_illegal_chars(text).lower()
    text = re.sub(r"[%s]" % re.escape(string.punctuation), " ", text)
    text = re.sub(r"\d+", " ", text)

    tokens = (w for w in text.split() if w not in stop_words and len(w) > 1)
    return re.sub(r"\s+", " ", " ".join(tokens)).strip()
