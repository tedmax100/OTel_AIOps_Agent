package after_resolution

import rego.v1

# 規則二：同一個 attribute 名字，在整份 resolved registry 裡不准有兩種型別。
#
# 這是依賴分層最危險的情況：團隊 registry 重新定義了一個 base 已經有的
# attribute，weaver 不會報錯，兩份定義並存，而所有 ref 都會解到 base 那份。
# 團隊以為自己覆寫了，其實只是造了一個沒有人用的孤兒。
type_name(t) := t if is_string(t)
type_name(t) := "enum" if is_object(t)

types_of(name) := {type_name(a.type) |
	some g in input.groups
	some a in g.attributes
	a.name == name
}

deny contains conflicting_definition(name) if {
	some g in input.groups
	some a in g.attributes
	name := a.name
	count(types_of(name)) > 1
}

conflicting_definition(name) := violation if {
	violation := {
		"id": "conflicting_attribute_definition",
		"type": "semconv_attribute",
		"category": "layering",
		"group": "(cross-registry)",
		"attr": name,
	}
}
