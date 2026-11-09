import json
import socket
import threading
import tempfile
from pathlib import Path
import pytest
from wowgm.control import ControlClient,ControlError

def test_unix_json_line_protocol(tmp_path):
    short=tempfile.TemporaryDirectory(prefix='wowgm-',dir='/tmp');path=str(Path(short.name)/'control.sock');server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(path);server.listen(1)
    received=[]
    def respond():
        with server:
            conn,_=server.accept()
            with conn:
                body=bytearray()
                while b'\n' not in body:body.extend(conn.recv(4096))
                received.append(json.loads(body))
                conn.sendall(b'{"ok":true,"settings":{"Rate.Health":2}}\n')
    t=threading.Thread(target=respond);t.start()
    r=ControlClient(path).request({'action':'get_config'});t.join(timeout=3)
    assert received==[{'action':'get_config'}] and r['settings']['Rate.Health']==2
    short.cleanup()

def test_missing_socket_is_friendly(tmp_path):
    with pytest.raises(ControlError,match='控制服务'):ControlClient(str(tmp_path/'absent')).request({'action':'get_config'})
