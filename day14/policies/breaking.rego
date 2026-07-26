package comparison_after_resolution

import rego.v1

# 在這個 package 裡：input = 新版 registry，data = baseline registry。
# 兩邊都是 resolved schema，所以 attribute 的鍵是 `name`（不是 `id`）。

# 只看 attribute_group（屬性池）那一份定義。signal group 上的同名 attribute 是
# ref 展開的副本，requirement_level 不同會讓 rule 產生多個輸出而整份 policy 被拒。
head_attrs[a.name] := a if {
	some g in input.groups
	g.type == "attribute_group"
	some a in g.attributes
}

baseline_attrs[a.name] := a if {
	some g in data.groups
	g.type == "attribute_group"
	some a in g.attributes
}

type_name(t) := t if is_string(t)
type_name(t) := "enum" if is_object(t)

finding(id, name, msg) := {
	"id": id,
	"type": "semconv_attribute",
	"category": "breaking_change",
	"group": "(registry)",
	"attr": sprintf("%s: %s", [name, msg]),
}

# 1. 直接消失：baseline 有、新版連 deprecated 都沒留
deny contains finding("attribute_removed", name, "在新版中完全消失，且沒有留下 deprecated 記錄") if {
	some name, _ in baseline_attrs
	not head_attrs[name]
}

# 2. 型別改掉：同一個名字，兩個版本的 type 不一樣
deny contains finding("attribute_type_changed", name, sprintf("型別從 %s 改成 %s", [old, new])) if {
	some name, a in baseline_attrs
	b := head_attrs[name]
	old := type_name(a.type)
	new := type_name(b.type)
	old != new
}

# 3. enum 值域縮小：拿掉 member 會讓既有資料變成非法值（加 member 不會）
deny contains finding("enum_member_removed", name, sprintf("enum 少了 %v", [gone])) if {
	some name, a in baseline_attrs
	b := head_attrs[name]
	is_object(a.type)
	is_object(b.type)
	old := {m.value | some m in a.type.members}
	new := {m.value | some m in b.type.members}
	gone := old - new
	count(gone) > 0
}
