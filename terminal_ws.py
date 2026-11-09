import base64
import hashlib
import json
import socket
import struct

import studio
from ensp_kit import Vrp
from vrp_security import clean_command

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_FRAME = 64 * 1024


class WebSocketClosed(Exception):
    pass


def handshake(handler):
    headers = handler.headers
    if (headers.get("Upgrade") or "").lower() != "websocket":
        raise ValueError("不是 WebSocket 请求")
    key = (headers.get("Sec-WebSocket-Key") or "").strip()
    if not key:
        raise ValueError("缺少 Sec-WebSocket-Key")
    version = (headers.get("Sec-WebSocket-Version") or "").strip()
    if version != "13":
        raise ValueError("只支持 WebSocket 13")
    accept = base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest()).decode("ascii")
    handler.send_response(101, "Switching Protocols")
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", accept)
    handler.end_headers()
    handler.wfile.flush()


def _read_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise WebSocketClosed()
        data.extend(chunk)
    return bytes(data)


def recv_frame(sock):
    first, second = _read_exact(sock, 2)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _read_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact(sock, 8))[0]
    if length > MAX_FRAME:
        raise ValueError("WebSocket 消息过大")
    if not masked:
        raise ValueError("浏览器帧必须使用掩码")
    mask = _read_exact(sock, 4)
    payload = bytearray(_read_exact(sock, length))
    for i in range(length):
        payload[i] ^= mask[i % 4]
    return opcode, bytes(payload)


def send_frame(sock, opcode, payload=b""):
    length = len(payload)
    if length < 126:
        header = bytes((0x80 | opcode, length))
    elif length < 65536:
        header = bytes((0x80 | opcode, 126)) + struct.pack("!H", length)
    else:
        header = bytes((0x80 | opcode, 127)) + struct.pack("!Q", length)
    sock.sendall(header + payload)


def send_json(sock, obj):
    send_frame(sock, 1, json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def _close(sock, code=1000):
    try:
        send_frame(sock, 8, struct.pack("!H", code))
    except OSError:
        pass


def serve(handler, port, lab_id, device):
    sock = handler.connection
    handshake(handler)
    handler.close_connection = True
    client = None
    try:
        client = Vrp("127.0.0.1", port, timeout=25)
        banner = client.open()
        client.cmd("screen-length 0 temporary", 6)
        send_json(sock, {"type": "ready", "device": device, "lab": lab_id,
                         "output": studio.strip_terminal(banner)})
        while True:
            opcode, payload = recv_frame(sock)
            if opcode == 8:
                _close(sock)
                break
            if opcode == 9:
                send_frame(sock, 10, payload)
                continue
            if opcode not in (1, 2):
                continue
            try:
                message = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                send_json(sock, {"type": "error", "message": "终端消息格式错误"})
                continue
            kind = message.get("type")
            if kind == "ping":
                send_json(sock, {"type": "pong"})
                continue
            if kind != "command":
                continue
            command = str(message.get("command") or "").strip()
            if not command:
                send_json(sock, {"type": "output", "output": ""})
                continue
            try:
                command = clean_command(command)
            except ValueError as exc:
                send_json(sock, {"type": "error", "message": str(exc)})
                continue
            try:
                output = client.cmd(command, timeout=60)
            except Exception as exc:
                send_json(sock, {"type": "error", "message": f"设备连接失败：{exc}"})
                send_json(sock, {"type": "closed"})
                break
            send_json(sock, {"type": "output", "command": command,
                             "output": studio.strip_terminal(output)})
    except WebSocketClosed:
        pass
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    except Exception as exc:
        try:
            send_json(sock, {"type": "error", "message": str(exc)})
        except (OSError, WebSocketClosed):
            pass
    finally:
        if client:
            client.close()
