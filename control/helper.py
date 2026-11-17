#!/usr/bin/env python3
"""Root-owned, local-only hot-config control. No database or arbitrary commands; narrowly validated account-level operation."""
import base64,datetime,json,math,os,pathlib,socket,socketserver,stat,struct,subprocess,tempfile,urllib.request,xml.etree.ElementTree as ET,re
CONFIG=pathlib.Path(os.environ.get('WOW_CONFIG','/etc/vmangos/mangosd.conf'))
SOCKET=pathlib.Path(os.environ.get('CONTROL_SOCKET','/run/wow-gm/control.sock'))
CREDENTIALS=pathlib.Path(os.environ.get('SOAP_CREDENTIALS','/run/secrets/soap.json'))
BACKUPS=pathlib.Path(os.environ.get('CONFIG_BACKUPS','/var/lib/realm-admin/config-backups'))
ALLOWED_UID=int(os.environ.get('WEB_UID','10001'))
RATES={'Rate.XP.Kill','Rate.XP.Quest','Rate.XP.Explore','Rate.Health','Rate.Mana','Rate.Energy','Rate.Drop.Money'}
EDITABLE=RATES|{'StartPlayerLevel','StartPlayerMoney'}
def read_settings(text):
 result={}
 for key in sorted(EDITABLE|{'MaxPlayerLevel'}):
  match=re.search(r'^'+re.escape(key)+r'\s*=\s*([^#\r\n]+)',text,re.M)
  if not match:raise ValueError('配置缺少字段：'+key)
  value=float(match.group(1).strip())
  if not math.isfinite(value):raise ValueError('配置含非法数值：'+key)
  result[key]=int(value) if value.is_integer() else value
 return result

def validate(values,current):
 if not isinstance(values,dict) or not values:raise ValueError('请提供至少一个要修改的参数。')
 if set(values)-EDITABLE:raise ValueError('包含不可热更新或不允许修改的参数。')
 clean={}
 for key,value in values.items():
  if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('参数必须是有限数字：'+key)
  if key in RATES:
   if not .1<=value<=20:raise ValueError(key+' 范围为 0.1–20。')
   clean[key]=round(float(value),6)
  elif key=='StartPlayerLevel':
   if int(value)!=value or not 1<=value<=min(60,current['MaxPlayerLevel']):raise ValueError('出生等级须为1至当前最高等级的整数。')
   clean[key]=int(value)
  else:
   if int(value)!=value or not 0<=value<=100000000:raise ValueError('出生金钱须为0至100000000铜币的整数。')
   clean[key]=int(value)
 return clean

def atomic_write(text):
 info=CONFIG.stat();fd,name=tempfile.mkstemp(prefix='.gm-config-',dir=CONFIG.parent)
 try:
  os.fchmod(fd,stat.S_IMODE(info.st_mode));os.fchown(fd,info.st_uid,info.st_gid)
  with os.fdopen(fd,'w') as out:out.write(text);out.flush();os.fsync(out.fileno())
  os.replace(name,CONFIG)
 finally:
  if os.path.exists(name):os.unlink(name)

def soap_command(command):
 credentials=json.loads(CREDENTIALS.read_text())
 token=base64.b64encode((credentials['username']+':'+credentials['password']).encode()).decode()
 body=('<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"><SOAP-ENV:Body><executeCommand xmlns="urn:MaNGOS"><command>'+command+'</command></executeCommand></SOAP-ENV:Body></SOAP-ENV:Envelope>').encode()
 req=urllib.request.Request('http://127.0.0.1:7878/',data=body,headers={'Content-Type':'text/xml; charset=utf-8','Authorization':'Basic '+token})
 try:
  with urllib.request.urlopen(req,timeout=5) as response:raw=response.read(65536)
 except Exception:raise RuntimeError('游戏控制接口未确认成功，请刷新账号档案核对后重试。') from None
 tree=ET.fromstring(raw)
 if any(node.tag.split('}')[-1]=='Fault' for node in tree.iter()):raise RuntimeError('游戏服务拒绝此操作。')
 return ' '.join(tree.itertext()).strip()

def reload_config():
 text=soap_command('reload config')
 if 'World config settings reloaded.' not in text:raise RuntimeError('游戏服务未确认热更新成功。')
 return text

def set_gm_level(request):
 if set(request)!={'action','username','level'}:raise ValueError('权限请求包含非法字段。')
 name=request.get('username');level=request.get('level')
 if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_]{1,16}',name):raise ValueError('账号名称无效。')
 if type(level) is not int or not 0<=level<=6:raise ValueError('GM等级范围为0–6。')
 protected={n.strip().upper() for n in os.getenv('PROTECTED_ACCOUNTS','__WEB_SERVICE,GMUI_SERVICE').split(',') if n.strip()}
 if name.upper() in protected:raise ValueError('不能修改服务账号权限。')
 text=soap_command(f'account set gmlevel {name.upper()} {level}')
 if f'You change security level of account {name.upper()} to {level}.' not in text:raise RuntimeError('游戏服务未确认权限修改，请刷新核对。')
 return {'ok':True,'level':level}

def process(request):
 if not isinstance(request,dict):raise ValueError('请求须为JSON对象。')
 if request.get('action')=='set_gm_level':return set_gm_level(request)
 old=CONFIG.read_text();current=read_settings(old)
 if request.get('action')=='get_config':
  try:
   with socket.create_connection((os.environ.get('WORLD_HOST','127.0.0.1'),int(os.environ.get('WORLD_PORT','8085'))),timeout=.5):active=True
  except OSError:active=False
  return {'ok':True,'settings':current,'server_online':active,'editable':sorted(EDITABLE)}
 if request.get('action')!='apply_config':raise ValueError('不支持的操作。')
 clean=validate(request.get('values'),current)
 changes={key:value for key,value in clean.items() if current[key]!=value}
 if not changes:return {'ok':True,'settings':current,'reloaded':False,'message':'参数未改变。'}
 new=old
 for key,value in changes.items():
  value=str(value).rstrip('0').rstrip('.') if isinstance(value,float) else str(value)
  new,n=re.subn(r'^'+re.escape(key)+r'\s*=.*$',key+' = '+value,new,flags=re.M)
  if n!=1:raise ValueError('配置字段重复或缺失：'+key)
 BACKUPS.mkdir(mode=0o700,parents=True,exist_ok=True)
 backup=BACKUPS/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.conf')
 backup.write_text(old);backup.chmod(0o600)
 atomic_write(new)
 try:reload_config()
 except Exception:
  atomic_write(old)
  try:reload_config()
  except Exception:pass
  raise RuntimeError('热更新未确认成功，配置文件已恢复，请检查游戏服务。')
 return {'ok':True,'settings':read_settings(new),'reloaded':True,'message':'参数已热更新，无需重启。'}

class Handler(socketserver.StreamRequestHandler):
 def handle(self):
  self.connection.settimeout(10)
  try:
   pid,uid,gid=struct.unpack('3i',self.connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
   if uid not in (0,ALLOWED_UID):raise PermissionError('调用进程未授权。')
   raw=self.rfile.readline(65537)
   if len(raw)>65536:raise ValueError('请求过大。')
   result=process(json.loads(raw))
  except (ValueError,PermissionError,RuntimeError) as error:result={'ok':False,'error':str(error)}
  except Exception:result={'ok':False,'error':'控制服务暂不可用，请检查运行日志。'}
  self.wfile.write((json.dumps(result,ensure_ascii=False)+'\n').encode())

if __name__=='__main__':
 SOCKET.parent.mkdir(parents=True,exist_ok=True)
 if SOCKET.exists():SOCKET.unlink()
 with socketserver.UnixStreamServer(str(SOCKET),Handler) as server:
  os.chown(SOCKET,0,ALLOWED_UID);SOCKET.chmod(0o660);server.serve_forever()
