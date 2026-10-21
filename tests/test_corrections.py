import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def body(**updates):
    return {"input": "قلم", "model_output": "قَلَمٌ", "corrected": "قَلَمَ", "request_id": "example", "note": "accusative", **updates}


def test_store_list_persist(settings, headers):
    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/corrections", headers=headers, json=body())
        assert response.status_code == 201
        result = response.json()
        assert set(result) == {"id", "created_at", "request_id", "diacritics_changed"}
        assert result["diacritics_changed"] == 1 and result["request_id"] == "example"
        assert result["created_at"].endswith("+00:00")
    with TestClient(create_app(settings)) as client:
        items = client.get("/v1/corrections", headers=headers).json()["items"]
        assert items == [{**body(), **result}]


@pytest.mark.parametrize("corrected", ["كتاب", "قلم إضافي", "قـلم", "قلم "])
def test_mismatch(client, headers, corrected):
    response = client.post("/v1/corrections", headers=headers, json=body(corrected=corrected))
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_correction", "reason": "base_text_mismatch"}
    assert client.get("/v1/corrections", headers=headers).json() == {"items": []}


def test_optional_and_invalid_model_output(client, headers):
    response = client.post("/v1/corrections", headers=headers, json={"input": "قلم", "model_output": "bad response", "corrected": "قَلَمٌ"})
    assert response.status_code == 201
    assert response.json()["request_id"]


def test_limit_order(client, headers):
    for _ in range(3):
        assert client.post("/v1/corrections", headers=headers, json=body()).status_code == 201
    items = client.get("/v1/corrections?limit=2", headers=headers).json()["items"]
    assert [item["id"] for item in items] == [3, 2]


def test_correction_length(client, headers):
    response = client.post("/v1/corrections", headers=headers, json=body(corrected="ب" * 5001))
    assert response.status_code == 413
