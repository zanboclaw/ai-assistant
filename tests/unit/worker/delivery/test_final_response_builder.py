from apps.worker.runtime.delivery.final_response_builder import build_final_response


def test_final_response_builder_strips_artifact_suffix():
    assert build_final_response("结果正文\n\n产出文件：/tmp/a.md") == "结果正文"

