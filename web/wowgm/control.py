import json
import socket

class ControlError(Exception):
    pass

class ControlClient:
    def __init__(self, path):
        self.path = path
    def request(self, payload):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(10)
                conn.connect(self.path)
                conn.sendall(json.dumps(payload, ensure_ascii=False).encode()+b"\n")
                data = bytearray()
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data)>65536:
                        raise ControlError("控制服务响应过长")
                    if b"\n" in data:
                        break
            result = json.loads(bytes(data).split(b"\n",1)[0])
            if not isinstance(result, dict) or not result.get("ok"):
                raise ControlError(result.get("error", "操作未完成") if isinstance(result,dict) else "控制服务返回格式异常")
            return result
        except ControlError:
            raise
        except (OSError, ValueError):
            raise ControlError("暂时无法连接服务器控制服务，请稍后再试") from None
