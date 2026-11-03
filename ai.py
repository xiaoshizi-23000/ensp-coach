import json
import os
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")

DEFAULT = {
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-flash",
    "api_key": "",
    "temperature": 0.4,
}

TUTOR_PROMPT = """你是「小狮子网络实验陪练」，带一个刚入行的网络工程师做华为 eNSP 实验。

规则：
1. 先判断他卡在哪一步、卡在哪个具体命令或哪个现象上，不要泛泛讲概念。
2. 他要提示，就给最小必要的下一步，不要一次把整段配置倒出来。只有他明确说"给我完整命令"才给。
3. 涉及 VRP 命令时写成一行一条，用行内代码，不要包大段代码块，除非他要求完整配置。
4. 他贴了设备回显，先读懂回显再回答，指出回显里哪一行能说明问题。
5. 中文，口语，短句。不要"作为一个 AI"这类话，不要列一堆要点，直接说怎么办。
6. 不确定的地方直说不确定，不要编造命令。
"""


def load_config():
    cfg = dict(DEFAULT)
    if os.path.exists(CONFIG_PATH):
        try:
            cfg.update(json.load(open(CONFIG_PATH, encoding="utf-8")))
        except Exception:
            pass
    key = os.environ.get("DEEPSEEK_API_KEY") or cfg.get("api_key") or ""
    cfg["api_key"] = key.strip()
    return cfg


def ready():
    return bool(load_config()["api_key"])


def chat(messages, temperature=None, timeout=60, system=None, json_mode=False, max_tokens=8192,
         thinking=None):
    cfg = load_config()
    if not cfg["api_key"]:
        return {"ok": False, "error": "还没配 DeepSeek 的 API Key，写到 ensp-ai/config.json 的 api_key 里就行。"}
    body = {
        "model": cfg["model"],
        "messages": [{"role": "system", "content": system or TUTOR_PROMPT}] + messages,
        "temperature": cfg["temperature"] if temperature is None else temperature,
        "stream": False,
        "max_tokens": max_tokens,
    }
    if thinking is not None:
        body["thinking"] = {"type": "enabled" if thinking else "disabled"}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(
        cfg["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + cfg["api_key"],
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        choice = data["choices"][0]
        return {"ok": True, "content": choice["message"]["content"],
                "finish": choice.get("finish_reason", "")}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        return {"ok": False, "error": f"DeepSeek 返回 {e.code}：{detail}"}
    except Exception as e:
        return {"ok": False, "error": f"调用失败：{e}"}
