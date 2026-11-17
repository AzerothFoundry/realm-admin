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

def helper_module():
    import importlib.util
    path=Path(__file__).resolve().parents[2]/'control/helper.py'
    spec=importlib.util.spec_from_file_location('control_helper_test',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

@pytest.mark.parametrize('payload',[
 {'action':'set_gm_level','username':'PLAYER; reload config','level':6},
 {'action':'set_gm_level','username':'PLAYER','level':7},
 {'action':'set_gm_level','username':'PLAYER','level':True},
 {'action':'set_gm_level','username':'GMUI_SERVICE','level':0},
 {'action':'set_gm_level','username':'PLAYER','level':6,'command':'other'},
])
def test_helper_rejects_unbounded_gm_commands(payload,monkeypatch):
    helper=helper_module();calls=[];monkeypatch.setattr(helper,'soap_command',lambda command:calls.append(command))
    with pytest.raises(ValueError):helper.process(payload)
    assert not calls

def test_helper_uses_exact_account_command_and_requires_ack(monkeypatch):
    helper=helper_module();calls=[]
    def command(text):calls.append(text);return 'You change security level of account PLAYER to 6.'
    monkeypatch.setattr(helper,'soap_command',command)
    assert helper.process({'action':'set_gm_level','username':'player','level':6})=={'ok':True,'level':6}
    assert calls==['account set gmlevel PLAYER 6']
    monkeypatch.setattr(helper,'soap_command',lambda _: 'Your security is low')
    with pytest.raises(RuntimeError):helper.process({'action':'set_gm_level','username':'PLAYER','level':6})
