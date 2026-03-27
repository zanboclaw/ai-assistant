from apps.worker.runtime.delivery.final_response_builder import build_final_response


def test_delivery_validation_path_keeps_main_body():
    assert build_final_response("主结果\n\n产出文件：a.txt") == "主结果"

