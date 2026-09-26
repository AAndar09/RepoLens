from fastapi.testclient import TestClient


def test_submit_public_github_repository(client: TestClient) -> None:
    response = client.post(
        "/api/v1/repositories",
        json={"github_url": "https://github.com/openai/openai-python.git/"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["github_url"] == "https://github.com/openai/openai-python"
    assert body["owner"] == "openai"
    assert body["name"] == "openai-python"
    assert body["status"] == "submitted"
    assert body["id"]


def test_duplicate_repository_is_rejected(client: TestClient) -> None:
    payload = {"github_url": "https://github.com/openai/openai-python"}

    assert client.post("/api/v1/repositories", json=payload).status_code == 201
    response = client.post("/api/v1/repositories", json=payload)

    assert response.status_code == 409
    assert response.json() == {"detail": "Repository has already been submitted"}


def test_non_github_or_non_repository_urls_are_rejected(client: TestClient) -> None:
    invalid_urls = [
        "http://github.com/openai/openai-python",
        "https://example.com/openai/openai-python",
        "https://github.com/openai",
        "https://github.com/openai/openai-python/issues",
        "https://user:secret@github.com/openai/openai-python",
    ]

    for github_url in invalid_urls:
        response = client.post("/api/v1/repositories", json={"github_url": github_url})
        assert response.status_code == 422, github_url
