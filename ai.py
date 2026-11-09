import json
import os
import re
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")
USAGE_PATH = os.path.join(BASE, "workspace", "ai_usage.jsonl")

DEFAULT = {
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-flash",
    "api_key": "",
    "temperature": 0.4,
    "privacy": "secrets",
    "cloud_enabled": True,
}

TUTOR_PROMPT = """你是「小狮子网络实验陪练」，带一个在岗工程师/认证考生做华为 eNSP 实验。

规则：
1. 回答必须具体、详细，直接解决他的问题。他卡住了就是要"现在怎么办"，不要泛泛讲概念。
2. 涉及配置的，给完整可执行的命令块：从 system-view 到 return 一次给全，按执行顺序包在一个代码块里，让他能整块复制粘贴。代码块后面用简短的行说明每条命令干什么、为什么。
3. 上下文里有他设备的当前真实配置、这一步的标准配置和程序比对的差异，回答要基于这些：先指出他已经有什么、缺什么，再给命令。
4. 他贴了设备回显，先读懂回显再回答，指出回显里哪一行能说明问题。
5. 他问原理就讲透，别怕长。
6. 中文，口语，直接。不要"作为一个 AI"这类话。不确定的地方直说不确定，不要编造命令。
"""

SECRET_RE = re.compile(
    r"(?i)(\b(?:password|pre-shared-key|authentication-key|key-string|shared-key|"
    r"community(?:\s+(?:read|write))?)(?:\s+(?:cipher|simple|irreversible-cipher))?)"
    r"[ \t]+(\S+)"
)
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
IPV6_RE = re.compile(r"\b(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}\b", re.I)


class Redactor:
    def __init__(self, level="secrets"):
        self.level = level if level in ("off", "secrets", "strict") else "secrets"
        self.ipv4 = {}
        self.ipv6 = {}

    def _map_ipv4(self, match):
        value = match.group(0)
        if value.startswith("255.") or value.startswith("0.0."):
            return value
        if value not in self.ipv4:
            index = len(self.ipv4) + 1
            self.ipv4[value] = f"192.0.2.{index % 254 or 1}"
        return self.ipv4[value]

    def _map_ipv6(self, match):
        value = match.group(0)
        if value.lower().startswith("2001:db8"):
            return value
        if value not in self.ipv6:
            index = len(self.ipv6) + 1
            self.ipv6[value] = f"2001:db8::{index:x}"
        return self.ipv6[value]

    def text(self, value):
        if self.level == "off":
            return value
        value = SECRET_RE.sub(r"\1 <已脱敏>", value)
        if self.level == "strict":
            value = IPV4_RE.sub(self._map_ipv4, value)
            value = IPV6_RE.sub(self._map_ipv6, value)
        return value

    def messages(self, messages):
        return [{"role": m.get("role", "user"), "content": self.text(str(m.get("content", "")))}
                for m in messages]


def load_config():
    cfg = dict(DEFAULT)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    key = os.environ.get("DEEPSEEK_API_KEY") or cfg.get("api_key") or ""
    cfg["api_key"] = key.strip()
    if cfg.get("privacy") not in ("off", "secrets", "strict"):
        cfg["privacy"] = "secrets"
    cfg["cloud_enabled"] = bool(cfg.get("cloud_enabled", True))
    return cfg


def ready():
    return bool(load_config()["api_key"])


def cloud_allowed():
    cfg = load_config()
    return bool(cfg.get("cloud_enabled", True))


def status():
    cfg = load_config()
    return {"configured": bool(cfg["api_key"]), "cloud": bool(cfg["cloud_enabled"]),
            "privacy": cfg["privacy"]}


def prepare_messages(messages, level=None):
    cfg = load_config()
    redactor = Redactor(level or cfg["privacy"])
    return redactor.messages(messages), cfg


def _log_usage(cfg, started, ok, usage=None, error=""):
    row = {
        "ts": time.time(),
        "model": cfg.get("model", ""),
        "privacy": cfg.get("privacy", ""),
        "ok": bool(ok),
        "elapsed_ms": round((time.time() - started) * 1000),
        "error": str(error)[:160],
    }
    if isinstance(usage, dict):
        row.update({
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "cache_hit_tokens": usage.get("prompt_cache_hit_tokens"),
            "cache_miss_tokens": usage.get("prompt_cache_miss_tokens"),
        })
    try:
        os.makedirs(os.path.dirname(USAGE_PATH), exist_ok=True)
        with open(USAGE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _request_body(messages, cfg, temperature, max_tokens, system, json_mode, thinking, stream=False):
    system_prompt = system or TUTOR_PROMPT
    if cfg.get("privacy") == "strict":
        system_prompt += (
            "\n隐私说明：发送前已把真实 IP 地址替换为 192.0.2.0/24 等文档地址，"
            "这些地址只用于保持拓扑关系。回答时不要把它们当作设备真实地址，"
            "请引用界面里的真实地址，或只给出命令结构并提醒用户替换地址。"
        )
    body = {
        "model": cfg["model"],
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "temperature": cfg["temperature"] if temperature is None else temperature,
        "stream": bool(stream),
        "max_tokens": max_tokens,
    }
    if thinking is not None:
        body["thinking"] = {"type": "enabled" if thinking else "disabled"}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    return body


def chat(messages, temperature=None, timeout=60, system=None, json_mode=False, max_tokens=8192,
         thinking=None):
    protected, cfg = prepare_messages(messages)
    if not cfg["api_key"]:
        return {"ok": False, "error": "还没配 DeepSeek 的 API Key，写到 ensp-ai/config.json 的 api_key 里就行。"}
    if not cfg["cloud_enabled"]:
        return {"ok": False, "error": "当前开启了本地规则模式，已阻止云端 AI 请求"}
    body = _request_body(protected, cfg, temperature, max_tokens, system, json_mode, thinking)
    req = urllib.request.Request(
        cfg["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + cfg["api_key"],
        },
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        choice = data["choices"][0]
        _log_usage(cfg, started, True, data.get("usage"))
        return {"ok": True, "content": choice["message"]["content"],
                "finish": choice.get("finish_reason", "")}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        _log_usage(cfg, started, False, error=f"HTTP {e.code}")
        return {"ok": False, "error": f"DeepSeek 返回 {e.code}：{detail}"}
    except Exception as e:
        _log_usage(cfg, started, False, error=type(e).__name__)
        return {"ok": False, "error": f"调用失败：{e}"}


def chat_stream(messages, temperature=None, timeout=120, system=None, max_tokens=8192,
                thinking=None):
    protected, cfg = prepare_messages(messages)
    if not cfg["api_key"]:
        raise RuntimeError("还没配 DeepSeek 的 API Key")
    if not cfg["cloud_enabled"]:
        raise RuntimeError("当前开启了本地规则模式，已阻止云端 AI 请求")
    body = _request_body(protected, cfg, temperature, max_tokens, system, None, thinking, stream=True)
    req = urllib.request.Request(
        cfg["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + cfg["api_key"],
        },
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = payload.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0].get("delta") or {}).get("content") or ""
                if delta:
                    yield delta
        _log_usage(cfg, started, True)
    except Exception as e:
        _log_usage(cfg, started, False, error=type(e).__name__)
        raise RuntimeError(f"流式调用失败：{e}") from e
