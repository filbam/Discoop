from discoop.qr import qr_matrix, qr_text

URL = "https://discord.com/ra/" + "A" * 43  # same length as a real QR login URL


def test_matrix_is_version_5_with_quiet_zone():
    rows = qr_matrix(URL)
    assert len(rows) == 45 and all(len(row) == 45 for row in rows)  # 37 modules + 2 * 4
    assert not any(rows[0]) and not any(row[0] for row in rows)


def test_text_uses_two_rows_per_line():
    lines = qr_text(URL).plain.split("\n")
    assert len(lines) == 23
    assert all(line == "▀" * 45 for line in lines)
