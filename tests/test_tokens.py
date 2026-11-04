from discoop.tokens import estimate_tokens, format_tokens


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a") == 1
    assert estimate_tokens("abc") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
    assert estimate_tokens("12345678") == 2
    assert estimate_tokens("123456789") == 3

    # Docstring must explicitly state that this is a rough estimate
    doc = estimate_tokens.__doc__ or ""
    assert "rough" in doc.lower()
    assert "estimate" in doc.lower()


def test_format_tokens():
    assert format_tokens(0) == "0"
    assert format_tokens(850) == "850"
    assert format_tokens(999) == "999"
    assert format_tokens(1000) == "1.0k"
    assert format_tokens(12400) == "12.4k"
    assert format_tokens(999999) == "1000.0k"
    assert format_tokens(1_000_000) == "1.0M"
    assert format_tokens(1_200_000) == "1.2M"
    assert format_tokens(12_345_678) == "12.3M"
