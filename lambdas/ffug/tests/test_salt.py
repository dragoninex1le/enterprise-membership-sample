"""The salt itself — primality, and the two properties the digest must have."""

import pytest

from ffug import salt


# --- primality is exact, not probabilistic, at these sizes -------------------


@pytest.mark.parametrize("n", [2, 3, 5, 17, 97, 7919, 2147483647, (1 << 61) - 1])
def test_known_primes_are_prime(n):
    assert salt.is_prime(n)


@pytest.mark.parametrize("n", [-7, 0, 1, 4, 9, 25, 91, 7917, 2147483649, 1 << 61])
def test_known_composites_are_not(n):
    assert not salt.is_prime(n)


def test_carmichael_numbers_are_rejected():
    """The numbers a naive Fermat test calls prime. Miller-Rabin must not."""
    for n in (561, 1105, 1729, 2465, 6601, 62745, 162401):
        assert not salt.is_prime(n)


def test_mint_returns_a_full_width_prime_as_a_decimal_string():
    minted = salt.mint_prime()

    assert isinstance(minted, str), "stored as a string so DynamoDB cannot hand it back as Decimal"
    assert minted.isdigit()
    value = int(minted)
    assert salt.is_prime(value)
    assert value.bit_length() == salt.PRIME_BITS, "top bit is set, so width is constant"


def test_successive_mints_differ():
    """Not a distribution test — a guard against a constant or a seeded PRNG."""
    assert len({salt.mint_prime() for _ in range(8)}) == 8


# --- the two properties the demo rests on -----------------------------------


def test_different_salts_give_different_digests_for_the_same_payload():
    """The visible property: tenant A and tenant B never agree on a payload."""
    payload = {"invoice": "INV-1", "amount": 100}

    assert salt.digest("11", payload) != salt.digest("13", payload)


def test_the_same_salt_and_payload_are_stable():
    """The property that makes it a fingerprint rather than a nonce."""
    payload = {"invoice": "INV-1", "amount": 100}

    assert salt.digest("11", payload) == salt.digest("11", payload)


def test_key_order_does_not_change_the_digest():
    """Without canonicalisation the same tenant would return two digests for the
    same payload, and the isolation demo would read as a leak."""
    assert salt.digest("11", {"a": 1, "b": 2}) == salt.digest("11", {"b": 2, "a": 1})


def test_the_separator_keeps_salt_and_payload_unambiguous():
    """Concatenating without a separator lets two different (salt, payload)
    pairs produce identical bytes. Here they must not."""
    assert salt.digest("1", "23") != salt.digest("12", "3")
