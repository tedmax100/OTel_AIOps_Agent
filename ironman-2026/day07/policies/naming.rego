package after_resolution

import rego.v1

# 規則一：attribute id 不得使用 camelCase
deny contains camel_case_attribute(group.id, attr.name) if {
	group := input.groups[_]
	attr := group.attributes[_]
	regex.match(`[a-z][A-Z]`, attr.name)
}

camel_case_attribute(group_id, attr_id) := violation if {
	violation := {
		"id": "camel_case_attribute",
		"type": "semconv_attribute",
		"category": "naming",
		"group": group_id,
		"attr": attr_id,
	}
}

# 規則二：正規化之後撞名——同一個概念被寫成兩個名字
# 把 userId / user_id / user.id 都正規化成 "userid" 再比對
normalized(name) := lower(replace(replace(name, "_", ""), ".", ""))

all_attr_names contains attr.name if {
	group := input.groups[_]
	attr := group.attributes[_]
}

deny contains duplicate_concept(a, b) if {
	a := all_attr_names[_]
	b := all_attr_names[_]
	a < b # 只報一次，不要 (a,b) 跟 (b,a) 各報一次
	normalized(a) == normalized(b)
}

duplicate_concept(a, b) := violation if {
	violation := {
		"id": "duplicate_concept",
		"type": "semconv_attribute",
		"category": "naming",
		"group": "(registry-wide)",
		"attr": sprintf("%s <-> %s", [a, b]),
	}
}

# 規則三：attribute id 必須有 namespace（至少一個點）
deny contains missing_namespace(group.id, attr.name) if {
	group := input.groups[_]
	attr := group.attributes[_]
	not contains(attr.name, ".")
}

missing_namespace(group_id, attr_id) := violation if {
	violation := {
		"id": "missing_namespace",
		"type": "semconv_attribute",
		"category": "naming",
		"group": group_id,
		"attr": attr_id,
	}
}
