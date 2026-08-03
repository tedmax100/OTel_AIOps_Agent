package before_resolution

import rego.v1

# base 擁有的 namespace。團隊 registry 只能 `ref` 它們，不能自己再定義一次。
platform_owned_prefixes := ["biz.", "app."]

deny contains reserved_namespace(group.id, attr.id) if {
	group := input.groups[_]
	attr := group.attributes[_]
	attr.id # 只看定義（有 id:），不看引用（ref:）
	some prefix in platform_owned_prefixes
	startswith(attr.id, prefix)
}

reserved_namespace(group_id, attr_id) := violation if {
	violation := {
		"id": "redefines_platform_attribute",
		"type": "semconv_attribute",
		"category": "layering",
		"group": group_id,
		"attr": attr_id,
	}
}
