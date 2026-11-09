import os
import re


MAX_COMMAND_LENGTH = 1000
MAX_PLAN_DEVICES = 16
MAX_COMMANDS_PER_DEVICE = 200
MAX_PLAN_COMMANDS = 500
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
READ_ONLY_RE = re.compile(r"^(?:display|ping|tracert)(?:\s|$)", re.I)
DESTRUCTIVE_RE = re.compile(
    r"^(?:reboot|schedule\s+reboot|reset\s+|clear\s+|delete(?:\s|$)|"
    r"format(?:\s|$)|erase\s+|restore\s+|factory-configuration\s+reset|"
    r"startup\s+saved-configuration|rollback\s+|undo\s+all(?:\s|$))",
    re.I,
)


def clean_command(command, read_only=False):
    if not isinstance(command, str):
        raise ValueError("命令必须是字符串")
    if any(x in command for x in ("\r", "\n", "\x00")):
        raise ValueError("一条命令不能包含换行或控制字符")
    command = command.strip()
    if not command:
        raise ValueError("命令不能为空")
    if len(command) > MAX_COMMAND_LENGTH:
        raise ValueError("命令过长")
    if read_only and not READ_ONLY_RE.match(command):
        raise ValueError("只读命令只允许 display、ping、tracert")
    if DESTRUCTIVE_RE.match(command):
        raise ValueError("破坏性命令不能通过自动执行通道下发：" + command.split()[0])
    return command


def clean_plan(plan, read_only=False):
    if not isinstance(plan, dict):
        raise ValueError("配置计划必须是设备名到命令数组的对象")
    if len(plan) > MAX_PLAN_DEVICES:
        raise ValueError("配置计划的设备数量过多")
    cleaned = {}
    total = 0
    for device, commands in plan.items():
        if not isinstance(device, str) or not device.strip() or len(device) > 64:
            raise ValueError("设备名无效")
        if not isinstance(commands, list):
            raise ValueError(f"{device} 的命令必须是数组")
        if len(commands) > MAX_COMMANDS_PER_DEVICE:
            raise ValueError(f"{device} 的命令数量过多")
        total += len(commands)
        if total > MAX_PLAN_COMMANDS:
            raise ValueError("一次下发的总命令数过多")
        cleaned[device] = [clean_command(c, read_only=read_only) for c in commands]
    return cleaned


def safe_id(value):
    value = str(value or "")
    if not ID_RE.fullmatch(value):
        raise ValueError("资源 ID 只能包含字母、数字、下划线和连字符")
    return value


def resource_path(folder, resource_id, suffix=".json"):
    resource_id = safe_id(resource_id)
    base = os.path.realpath(folder)
    path = os.path.realpath(os.path.join(base, resource_id + suffix))
    try:
        inside = os.path.commonpath((base, path)) == base
    except ValueError:
        inside = False
    if not inside:
        raise ValueError("资源路径越界")
    return path
