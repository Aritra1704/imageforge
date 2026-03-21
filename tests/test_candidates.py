def test_candidate_selection_behavior(client, sample_generate_payload, storage):
    generate_response = client.post("/api/images/generate", json=sample_generate_payload)
    request_id = generate_response.json()["request_id"]
    candidates = generate_response.json()["results"][0]["candidates"]
    first_candidate_id = candidates[0]["candidate_id"]
    second_candidate_id = candidates[1]["candidate_id"]

    first_select = client.post(f"/api/images/candidates/{first_candidate_id}/select")
    assert first_select.status_code == 200
    assert first_select.json()["candidate"]["is_selected"] is True

    second_select = client.post(f"/api/images/candidates/{second_candidate_id}/select")
    assert second_select.status_code == 200
    assert second_select.json()["candidate"]["candidate_id"] == second_candidate_id
    assert second_select.json()["candidate"]["is_selected"] is True
    assert (
        second_select.json()["candidate"]["selected_asset_relative_path"]
        == second_select.json()["candidate"]["relative_path"]
    )
    assert (
        second_select.json()["candidate"]["selected_asset_public_url"]
        == second_select.json()["candidate"]["public_url"]
    )
    assert not (storage.root / "selected" / request_id).exists()

    detail_response = client.get(f"/api/images/requests/{request_id}")
    detail = detail_response.json()
    assert detail["request"]["recommended_candidate_id"] == detail["candidates"][0]["candidate_id"]
    assert detail["selected_candidate"]["candidate_id"] == second_candidate_id
    assert (
        detail["selected_candidate"]["selected_asset_relative_path"]
        == detail["selected_candidate"]["relative_path"]
    )
    assert detail["candidates"][0]["rank"] == 1
    assert detail["candidates"][0]["quality_score"] == 10.0
    assert detail["candidates"][0]["relevance_score"] == 10.0
    selected_candidates = [candidate for candidate in detail["candidates"] if candidate["is_selected"]]
    assert len(selected_candidates) == 1
    assert selected_candidates[0]["candidate_id"] == second_candidate_id
    assert "absolute_path" not in detail["selected_candidate"]


def test_absolute_path_not_leaked_in_api_responses(client, sample_generate_payload):
    generate_response = client.post("/api/images/generate", json=sample_generate_payload)
    request_id = generate_response.json()["request_id"]
    candidate_id = generate_response.json()["results"][0]["candidates"][0]["candidate_id"]

    detail_response = client.get(f"/api/images/requests/{request_id}")
    candidates_response = client.get(f"/api/images/requests/{request_id}/candidates")
    select_response = client.post(f"/api/images/candidates/{candidate_id}/select")

    assert "absolute_path" not in detail_response.json()["candidates"][0]
    assert "absolute_path" not in candidates_response.json()["candidates"][0]
    assert "absolute_path" not in select_response.json()["candidate"]


def test_list_requests_filters_by_provider(client, sample_generate_payload):
    client.post("/api/images/generate", json=sample_generate_payload)
    response = client.get("/api/images/requests", params={"provider": "comfyui"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert len(body["items"]) == 1
    assert body["items"][0]["providers"] == ["comfyui"]
