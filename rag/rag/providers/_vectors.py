"""Vector arithmetic every embedding provider needs.

Private to `rag.providers` — the leading underscore says so. Nothing outside
this package should import it, because nothing outside this package should be
doing arithmetic on embeddings.

**Why this module exists at all.** `l2_normalise` lived in `gemini.py` as a
private function until the fake provider needed it too. The three ways out were:
copy it, have `fake.py` import it from `gemini.py`, or move it here.

Copying loses: the invariant below is subtle enough that two copies will
eventually disagree, and the disagreement would be invisible — no error, just
quietly worse ranking. Importing from `gemini.py` loses harder: the fake would
then drag in the Google SDK, destroying the whole point of the lazy provider
imports in `base.py`.

So it moves. The function body is unchanged.
"""

import math


def l2_normalise(vector: list[float]) -> list[float]:
    """Scale a vector to unit length.

    **Not optional at 768 dimensions.** `gemini-embedding-001` returns
    unit-length vectors only at its native 3072 dimensions. Ask for a truncated
    output — which decision 0002 does, for a 4x smaller and faster index — and
    the result is no longer normalised, because chopping off dimensions removes
    part of the length.

    Cosine similarity divides by both vectors' magnitudes, so in principle it
    tolerates that. In practice Qdrant normalises once at insertion for speed
    and assumes what it stored was sensible, and inconsistent magnitudes across
    the corpus distort scores in ways that are invisible — no error, just
    quietly worse ranking. Normalising at the seam means every vector that
    reaches the index is unit length regardless of provider.

    That last sentence is why this is shared rather than Gemini's private
    business: a provider whose vectors are not unit length is not a drop-in
    substitute for one whose vectors are, and a load test run against
    differently-scaled vectors would not be measuring the same system.

    The zero guard is for defence, not realism: a zero-length vector has no
    direction to preserve, and dividing by zero would poison the index with NaN.
    """
    magnitude = math.sqrt(sum(value * value for value in vector))

    if magnitude == 0.0:
        return vector

    return [value / magnitude for value in vector]
