from heuristic_planner_runtime import infer_structured_steps_from_user_input


def test_infer_structured_steps_from_json_extract_to_file():
    planned = infer_structured_steps_from_user_input(
        "请提取 planner 字段，从 /tmp/a.json 写入 /tmp/out.txt",
        extract_path_from_text=lambda _text: "/tmp/a.json",
    )

    assert [step["tool"] for step in planned] == ["read_json", "json_extract", "file_write"]
    assert planned[1]["input"]["path"] == "planner"


def test_infer_structured_steps_for_http_request_summary():
    planned = infer_structured_steps_from_user_input(
        "帮我请求 https://example.com/api 然后整理接口返回结果",
        extract_path_from_text=lambda _text: None,
    )

    assert [step["tool"] for step in planned] == ["http_request", "summarize_text"]
    assert planned[0]["input"]["url"] == "https://example.com/api"
