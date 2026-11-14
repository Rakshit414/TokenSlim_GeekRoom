from invoice_service import format_invoice_id, generate_invoice_metadata

def test_format_invoice_id():
    assert format_invoice_id(42) == "INV-00042"
    assert format_invoice_id(1) == "INV-00001"
    assert format_invoice_id(12345) == "INV-12345"
