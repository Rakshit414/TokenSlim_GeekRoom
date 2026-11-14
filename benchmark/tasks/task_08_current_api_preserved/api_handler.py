from pydantic import BaseModel, Field

class ItemPayload(BaseModel):
    name: str = Field(..., min_length=1, description="Item name")
    price: float = Field(..., gt=0.0, description="Price must be positive")

def handle_create_item(payload_dict: dict) -> dict:
    item = ItemPayload.model_validate(payload_dict)
    # Bug: returns 200 instead of HTTP 201 Created
    return {
        "status_code": 200,
        "item": item.model_dump()
    }
