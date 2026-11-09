import ipaddress
import re


NOISE_PREFIXES = (
    "#", "!", "return", "quit", "undo shutdown", "screen-length", "user-interface",
    "authentication-mode", "idle-timeout", "protocol inbound",
)
IGNORE_ACTUAL_PREFIXES = (
    "<", "[", "display current-configuration", "building configuration",
    "current configuration", "info:",
)
INTERFACE_RE = re.compile(r"^interface\s+(.+)$", re.I)
OSPF_RE = re.compile(r"^ospf\s+(\d+)(?:\s+router-id\s+(\S+))?$", re.I)
BGP_RE = re.compile(r"^bgp\s+(\d+)$", re.I)
AREA_RE = re.compile(r"^area\s+(\S+)$", re.I)
VLAN_RE = re.compile(r"^vlan\s+(\d+)$", re.I)
ACL_RE = re.compile(r"^acl\s+(?:(?:number|name)\s+)?(\S+)$", re.I)
ROUTE_POLICY_RE = re.compile(r"^route-policy\s+(\S+)\s+(?:permit|deny)\s+node\s+(\d+)$", re.I)
VIEW_PATTERNS = (
    (re.compile(r"^isis(?:\s+\d+)?$", re.I), lambda m: m.group(0).lower()),
    (re.compile(r"^rip(?:\s+\d+)?$", re.I), lambda m: m.group(0).lower()),
    (re.compile(r"^ipv4-family(?:\s+\S+)?$", re.I), lambda m: m.group(0).lower()),
    (re.compile(r"^ip\s+vpn-instance\s+(\S+)$", re.I), lambda m: "ip vpn-instance " + m.group(1).lower()),
    (re.compile(r"^user-interface\s+(.+)$", re.I), lambda m: "user-interface " + m.group(1).lower()),
    (re.compile(r"^aaa$", re.I), lambda m: "aaa"),
    (re.compile(r"^ip\s+pool\s+(\S+)$", re.I), lambda m: "ip pool " + m.group(1).lower()),
    (re.compile(r"^nat\s+address-group\s+(\d+)$", re.I), lambda m: "nat address-group " + m.group(1)),
)


def _mask_to_prefix(mask):
    try:
        return str(ipaddress.IPv4Network("0.0.0.0/" + str(mask)).prefixlen)
    except (ipaddress.NetmaskValueError, ValueError):
        return None


def _normalize_area(value):
    try:
        return str(int(ipaddress.IPv4Address(value)))
    except ipaddress.AddressValueError:
        return str(value).lower()


def normalize_line(line):
    line = " ".join(str(line).strip().split())
    low = line.lower()
    if low.startswith("ip address "):
        parts = line.split()
        if len(parts) >= 4:
            prefix = _mask_to_prefix(parts[3])
            if prefix is not None:
                parts[3] = prefix
                line = " ".join(parts)
    return line


def _interface_name(name):
    value = re.sub(r"\s+", "", str(name)).lower()
    value = value.replace("gigabitethernet", "ge").replace("ethernet", "eth")
    value = value.replace("vlanif", "vlanif")
    return value


def _view_for(command, current_path):
    interface = INTERFACE_RE.match(command)
    if interface:
        return "interface " + _interface_name(interface.group(1)), None
    ospf = OSPF_RE.match(command)
    if ospf:
        extra = f"router-id {ospf.group(2)}" if ospf.group(2) else None
        return "ospf " + ospf.group(1), extra
    bgp = BGP_RE.match(command)
    if bgp:
        return "bgp " + bgp.group(1), None
    if current_path and current_path[-1].startswith("ospf "):
        area = AREA_RE.match(command)
        if area:
            return "area " + _normalize_area(area.group(1)), None
    vlan = VLAN_RE.match(command)
    if vlan:
        return "vlan " + vlan.group(1), None
    acl = ACL_RE.match(command)
    if acl:
        return "acl " + acl.group(1).lower(), None
    policy = ROUTE_POLICY_RE.match(command)
    if policy:
        return f"route-policy {policy.group(1).lower()} {policy.group(2)}", None
    for pattern, make_key in VIEW_PATTERNS:
        if pattern.match(command):
            return make_key(pattern.match(command)), None
    return None


def _is_noise(command):
    low = command.lower()
    return any(low.startswith(prefix) for prefix in NOISE_PREFIXES)


def _label_for(path):
    if not path:
        return "系统视图"
    return " › ".join(path)


def _add_leaf(groups, path, command):
    item = groups.setdefault(path, {"lines": [], "negations": [], "label": _label_for(path)})
    item["lines"].append(normalize_line(command))


def _remove_positive(groups, path, target):
    item = groups.get(path)
    if not item:
        return
    item["lines"] = [line for line in item["lines"] if not _undo_matches(line, target)]


def _remove_negation(groups, path, command):
    item = groups.get(path)
    if not item:
        return
    target = command
    item["negations"] = [neg for neg in item["negations"] if not _same_family(neg, target)]


def _same_family(negation, command):
    left = negation.split()
    right = command.split()
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    return longer[:len(shorter)] == shorter


def _undo_matches(actual_line, undo_command):
    target = undo_command.split()
    actual = actual_line.split()
    return len(actual) >= len(target) and actual[:len(target)] == target


def build_expected(commands):
    groups = {}
    path = []
    for raw in commands or []:
        command = normalize_line(raw)
        if not command:
            continue
        low = command.lower()
        if low == "system-view":
            path = []
            continue
        if low == "return":
            path = []
            continue
        if low == "quit":
            if path:
                path.pop()
            continue
        if low.startswith("undo "):
            target = command[5:].strip()
            if not target:
                continue
            _remove_positive(groups, tuple(path), target)
            item = groups.setdefault(tuple(path), {"lines": [], "negations": [], "label": _label_for(path)})
            item["negations"].append(target)
            continue
        view = _view_for(command, path)
        if view:
            key, extra = view
            path.append(key)
            if extra:
                _remove_negation(groups, tuple(path), extra)
                _add_leaf(groups, tuple(path), extra)
            continue
        if _is_noise(command):
            continue
        _remove_negation(groups, tuple(path), command)
        _add_leaf(groups, tuple(path), command)
    for item in groups.values():
        item["lines"] = sorted(set(item["lines"]))
        item["negations"] = sorted(set(item["negations"]))
    return {path: item for path, item in groups.items() if item["lines"] or item["negations"]}


def parse_config(text):
    groups = {}
    path = []
    stack = []
    for raw in str(text or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        low = stripped.lower()
        if any(low.startswith(prefix) for prefix in IGNORE_ACTUAL_PREFIXES):
            continue
        if stripped == "#":
            path, stack = [], []
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        while stack and indent <= stack[-1][0]:
            stack.pop()
            if path:
                path.pop()
        view = _view_for(stripped, path)
        if view:
            key, extra = view
            path.append(key)
            stack.append((indent, key))
            if extra:
                _add_leaf(groups, tuple(path), extra)
            continue
        if _is_noise(stripped):
            continue
        if low.startswith("undo "):
            item = groups.setdefault(tuple(path), {"lines": [], "negations": [], "label": _label_for(path)})
            item["negations"].append(stripped[5:].strip())
        else:
            _add_leaf(groups, tuple(path), stripped)
    for item in groups.values():
        item["lines"] = sorted(set(item["lines"]))
        item["negations"] = sorted(set(item["negations"]))
    return {path: item for path, item in groups.items() if item["lines"] or item["negations"]}


def _vlan_sets(lines):
    batch, single = set(), set()
    for line in lines:
        match = re.fullmatch(r"vlan batch (.+)", line, re.I)
        if match:
            batch.update(match.group(1).split())
            continue
        match = re.fullmatch(r"vlan (\d+)", line, re.I)
        if match:
            single.add(match.group(1))
    return batch, single


def _line_present(line, actual_lines, batch, single):
    if line in actual_lines:
        return True
    match = re.fullmatch(r"vlan (\d+)", line)
    if match and match.group(1) in batch:
        return True
    match = re.fullmatch(r"vlan batch (.+)", line)
    if match and set(match.group(1).split()) <= (batch | single):
        return True
    return False


def _negation_present(target, actual, parent_path, actual_paths):
    for line in actual["negations"]:
        if line == target or _undo_matches(line, target):
            return True
    view = _view_for(target, parent_path)
    if view:
        key = view[0]
        for path in actual_paths:
            if len(path) > len(parent_path) and path[:len(parent_path)] == parent_path and path[-1] == key:
                return False
    return not any(_undo_matches(line, target) for line in actual["lines"])


def compare_config(expected, actual):
    all_actual = []
    all_negations = []
    for item in actual.values():
        all_actual.extend(item["lines"])
        all_negations.extend(item["negations"])
    batch, single = _vlan_sets(all_actual)
    missing = []
    extra = []
    hit = 0
    total = 0
    actual_paths = set(actual)
    for path, want in expected.items():
        have = actual.get(path, {"lines": [], "negations": [], "label": want["label"]})
        scope = set(have["lines"])
        for line in want["lines"]:
            total += 1
            if _line_present(line, scope, batch, single):
                hit += 1
            else:
                missing.append(want["label"] + " → " + line)
        for target in want["negations"]:
            total += 1
            if _negation_present(target, have, path, actual_paths):
                hit += 1
            else:
                missing.append(want["label"] + " → 仍存在 " + target)
    for path, want in expected.items():
        if not path or not path[-1].startswith("interface "):
            continue
        have = actual.get(path, {"lines": []})
        allowed = set(want["lines"])
        for line in have["lines"]:
            if line in allowed or _is_noise(line):
                continue
            if line in all_negations:
                continue
            extra.append(want["label"] + " → " + line)
    return {"hit": hit, "total": total, "missing": missing, "extra": extra}
