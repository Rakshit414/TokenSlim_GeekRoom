from api_handler import handle_create_item, ItemPayload

def test_create_item_status_and_schema():
    res = handle_create_item({"name": "Widget", "price": 9.99})
    assert res["status_code"] == 201
    assert res["item"]["name"] == "Widget"
    # Ensure Field definitions were preserved
    assert ItemPayload.model_fields["price"].description == "Price must be positive"
