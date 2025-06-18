# Coding Conventions for AI Assistant

**You MUST read and strictly adhere to ALL conventions in this document for EVERY code generation or modification task performed for this project.**
Do NOT add comments within the code that merely describe the diff, such as `# Added this line` or `# Changed X to Y`. Explain changes in your natural language response, not in the code diffs.
Adhere strictly to the user's request. If a request is ambiguous or critical information is missing, **always clarify by asking focused questions** before proceeding. Do not generate code until the necessary information is provided.

## Architecture

When writing code, you MUST follow these principles:

- Follow repository pattern for data access
- Use service layer for business logic
- Factory pattern for object creation
- Keep controllers (API endpoints) thin
- Keep the code as simple as possible. Avoid unnecessary complexity.
- Use self-explanatory identifier names rather than comments
- When comments are used, they should add useful information that is not readily apparent from the code itself.
- Do not add docstrings to methods/functions, they should be clear in and of themselves.
- Assume that the absolute latest version of Python is used.

### Modern Python and Type Safety:

- Comprehensive type hinting is MANDATORY for all function signatures (parameters and return types) and significant variable declarations.
- All code MUST pass `basedpyright` type checking without errors or warnings.
  - While processing data prefer using Pydantic models over untyped dictionary modifications
- Write code using the latest stable Python version and its modern features, such as:
  - PEP604: use `int | None` over `typing.Optional[int]`
  - PEP636: pattern matching using `match/case`
  - PEP695: use the new generics syntax `ClassA[T: str]` and `func[T](a: T, b: T) -> T`

Example code:

```python
class UnitQuantity(BaseModel):
    value: int

class KilogramQuantity(BaseModel):
    value: float

OrderQuantity = UnitQuantity | KilogramQuantity

an_order_qty_in_units = UnitQuantity(value=10)
an_order_qty_in_kg = KilogramQuantity(value=2.5)

def quantity_label(oq: OrderQuantity) -> str:
    match (oq):
        case UnitQuantity(value=n):
            return f'{n} units'
        case KilogramQuantity(value=n):
            return f'{n} kg'

label = quantity_label(an_order_qty_in_kg)
print(label)
```

## Testing

Use `GIVEN`, `WHEN`, `THEN` (or `AND`) comments for the different parts of a test.
When an endpoint is tested that has a JSON response always use `expected_structure` (no matter how deep and verbose) in tests so that the response structure becomes clear:

```python
def test_get_step(self):
    # GIVEN a step exists in the database
    step = create_test_step(self.session)

    # WHEN we request the step
    response = self.client.get(f"/steps/{step.id}")

    # THEN the successful response matches the expected structure
    expected_structure = {
        "id": step.id,
        "header": None,
        "content": None,
        "notes": {
            "id": step.notes_id,
            "type": "notes",
            "document": {
                "type": "doc",
                "content": [],
            },
        },
        "settings": {
            "theme": "default",
            "template": "document",
            "background": None,
            "layout": "cover",
            "content": True,
            "header": False,
            "questions": False,
        },
    }
    assert response.status_code == 200
    assert response.json() == expected_structure
```
