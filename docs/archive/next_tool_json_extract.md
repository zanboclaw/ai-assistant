# next tool: json_extract

目标：
- 从 JSON 对象中提取指定字段
- 支持路径：
  - a.b.c
  - modules.0
  - json.args.q

输入：
{
  "data": {...},
  "path": "modules.0"
}

输出：
{
  "value": ...
}
