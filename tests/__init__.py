"""Tests for the parts of this project that do not need the private exports.

Everything under `data/` is a raw utility export carrying an account holder's
name, service address and account numbers, so it is gitignored and cannot be
checked in as a fixture. That is a constraint on the tests, not an excuse for
skipping them: the transcribed tariffs, the physics, the prose helpers and the
architectural invariants are all checkable without a single reading, and those
are exactly the places where a silent error would poison every figure on the
page.

    python3 -m unittest discover -s tests -v
"""
