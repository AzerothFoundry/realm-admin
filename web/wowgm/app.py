import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import pymysql
from . import auth
from .db import GameDB
from .control import ControlClient, ControlError
from .config import CONFIG, validate

HERE=Path(__file__).parent
RACES={1:'人类',2:'兽人',3:'矮人',4:'暗夜精灵',5:'亡灵',6:'牛头人',7:'侏儒',8:'巨魔'}
CLASSES={1:'战士',2:'圣骑士',3:'猎人',4:'盗贼',5:'牧师',7:'萨满祭司',8:'法师',9:'术士',11:'德鲁伊'}

def public(account):
    return {k:v for k,v in account.items() if k not in {'v','s','sessionkey'}} if account else None

class Limiter:
    def __init__(self): self.events=defaultdict(deque); self.lock=threading.Lock()
    def take(self,key,limit,window):
        now=time.monotonic()
        with self.lock:
            events=self.events[key]
            while events and events[0]<now-window: events.popleft()
            if len(events)>=limit: return False
            events.append(now)
            if len(self.events)>10000:
                self.events={k:v for k,v in self.events.items() if v and v[-1]>now-3600}
                self.events=defaultdict(deque,self.events)
            return True

def secret_key():
    if os.getenv('SECRET_KEY'):
        value=os.environ['SECRET_KEY']
        if len(value)<32: raise RuntimeError('SECRET_KEY must contain at least 32 characters')
        return value
    root=Path(os.getenv('DATA_DIR',str(HERE.parent/'.local-data')))
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=root/'secret-key'
    try:
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as f: f.write(secrets.token_hex(48))
    except FileExistsError: pass
    return path.read_text().strip()

def create_app(db=None,control=None,settings=None):
    options=settings or {}
    key=options.get('secret_key') or secret_key()
    secure=options.get('cookie_secure',os.getenv('COOKIE_SECURE','0')=='1')
    protected={n.strip().upper() for n in options.get('protected_accounts',os.getenv('PROTECTED_ACCOUNTS','__WEB_SERVICE,GMUI_SERVICE')).split(',') if n.strip()}
    database=db if db is not None else GameDB()
    controller=control if control is not None else ControlClient(os.getenv('CONTROL_SOCKET','/run/wow-gm/control.sock'))
    serializer=URLSafeTimedSerializer(key,salt='wow-gm-session-v1')
    limiter=Limiter()
    app=FastAPI(title='艾泽拉斯 · 测试控制台',docs_url=None,redoc_url=None,openapi_url=None)
    app.state.db=database;app.state.control=controller;app.state.limiter=limiter
    app.mount('/static',StaticFiles(directory=HERE/'static'),name='static')
    templates=Jinja2Templates(directory=HERE/'templates')
    templates.env.globals.update(races=RACES,classes=CLASSES,config_fields=CONFIG)

    def page(request,name,status_code=200,**context):
        return templates.TemplateResponse(request=request,name=name,context={'user':public(request.state.user),'csrf':request.state.session['csrf'],**context},status_code=status_code)
    def current(request,gm=False):
        user=request.state.user
        if not user: raise HTTPException(401,'请先登录')
        if gm and int(user['gmlevel'])<6: raise HTTPException(403,'此页面仅供管理员使用')
        return user
    def limited(request,kind,limit,window,subject=''):
        ip=request.client.host if request.client else 'unknown'
        if not limiter.take((kind,ip,subject),limit,window): raise HTTPException(429,'操作过于频繁，请稍后再试')
    async def form(request):
        data=await request.form(max_fields=30,max_files=0)
        if any(len(data.getlist(k))!=1 for k in data): raise HTTPException(400,'表单参数重复')
        token=data.get('csrf','')
        if not isinstance(token,str) or not hmac.compare_digest(token,request.state.session['csrf']):
            raise HTTPException(403,'页面校验已失效，请刷新页面后重试')
        return data
    def signed_in(request,account):
        request.state.session={'uid':int(account['id']),'fp':auth.fingerprint(account,key),'csrf':secrets.token_urlsafe(32)}

    @app.middleware('http')
    async def session(request,call_next):
        if int(request.headers.get('content-length','0') or 0)>16384:
            return HTMLResponse('请求内容过长',413)
        payload=None
        try:
            payload=serializer.loads(request.cookies.get('wowgm',''),max_age=8*3600)
            if not isinstance(payload,dict) or not isinstance(payload.get('csrf'),str):payload=None
        except (BadSignature,SignatureExpired,TypeError,ValueError):pass
        request.state.session=payload or {'uid':None,'csrf':secrets.token_urlsafe(32)}
        request.state.user=None
        uid=request.state.session.get('uid')
        if isinstance(uid,int) and uid>0:
            try:
                account=database.account(uid)
                if account and hmac.compare_digest(request.state.session.get('fp',''),auth.fingerprint(account,key)):
                    request.state.user=account
                else:request.state.session={'uid':None,'csrf':secrets.token_urlsafe(32)}
            except pymysql.MySQLError:
                return HTMLResponse('游戏账号服务暂时不可用，请稍后再试',503)
        response=await call_next(request)
        if not request.url.path.startswith('/static/'):
            response.set_cookie('wowgm',serializer.dumps(request.state.session),max_age=8*3600,httponly=True,secure=secure,samesite='lax',path='/')
            response.headers['Cache-Control']='no-store'
        response.headers['X-Frame-Options']='DENY'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' data:; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request,exc):
        if exc.status_code==401:return RedirectResponse('/login',303)
        return page(request,'error.html',exc.status_code,message=exc.detail)
    @app.exception_handler(pymysql.MySQLError)
    async def db_error(request,exc):return page(request,'error.html',503,message='游戏账号服务暂时不可用，请稍后再试')
    @app.get('/healthz')
    def health():return {'ok':True}
    @app.get('/')
    def home(request:Request):return RedirectResponse('/me' if request.state.user else '/login',303)
    @app.get('/login')
    def login_page(request:Request):return page(request,'auth.html',mode='login')
    @app.post('/login')
    async def login(request:Request):
        data=await form(request);limited(request,'login',20,600)
        try:name=auth.username(str(data.get('username','')))
        except ValueError:return page(request,'auth.html',400,mode='login',error='账号或密码不正确')
        limited(request,'login-account',10,600,name)
        account=database.find(name)
        if not account or not auth.verify(name,str(data.get('password','')),account['s'],account['v']):
            return page(request,'auth.html',400,mode='login',error='账号或密码不正确')
        signed_in(request,account)
        return RedirectResponse('/me',303)
    @app.get('/register')
    def register_page(request:Request):return page(request,'auth.html',mode='register')
    @app.post('/register')
    async def register(request:Request):
        data=await form(request);limited(request,'register',5,3600)
        if set(data)-{'username','password','confirm_password','csrf'}:raise HTTPException(400,'注册表单包含不允许的字段')
        try:
            name=auth.username(str(data.get('username','')));secret=str(data.get('password',''));auth.password(secret)
            if secret!=data.get('confirm_password'):raise ValueError('两次输入的密码不一致')
            s,v=auth.credentials(name,secret);account_id=database.register(name,s,v)
        except ValueError as e:return page(request,'auth.html',400,mode='register',error=str(e))
        account=database.account(account_id);signed_in(request,account)
        return RedirectResponse('/me',303)
    @app.post('/logout')
    async def logout(request:Request):
        await form(request);request.state.session={'uid':None,'csrf':secrets.token_urlsafe(32)}
        return RedirectResponse('/login',303)
    @app.get('/me')
    def me(request:Request):
        user=current(request)
        return page(request,'me.html',characters=database.characters(user['id']))
    @app.post('/me/password')
    async def change_password(request:Request):
        user=current(request);data=await form(request);limited(request,'change-password',8,600,str(user['id']))
        try:
            if not auth.verify(user['username'],str(data.get('current_password','')),user['s'],user['v']):raise ValueError('当前密码不正确')
            new=str(data.get('new_password',''));auth.password(new)
            if new!=data.get('confirm_password'):raise ValueError('两次输入的新密码不一致')
            s,v=auth.credentials(user['username'],new)
            if not database.set_password(user['id'],s,v,expected_v=user['v']):raise ValueError('账号信息已变化，请重新登录后重试')
            account=database.account(user['id']);signed_in(request,account)
            return page(request,'me.html',characters=database.characters(user['id']),notice='密码已更新，今后请使用新密码登录游戏。其他网页会话已失效。')
        except ValueError as e:return page(request,'me.html',400,characters=database.characters(user['id']),error=str(e))
    @app.get('/admin/accounts')
    def accounts(request:Request,q:str=''):
        current(request,gm=True)
        return page(request,'accounts.html',accounts=database.accounts(q[:32]),query=q[:32])
    @app.get('/admin/accounts/{account_id}')
    def account_detail(request:Request,account_id:int):
        current(request,gm=True);target=database.account(account_id)
        if not target:raise HTTPException(404,'账号不存在')
        return page(request,'account.html',target=public(target),characters=database.characters(account_id),can_reset=int(target['gmlevel'])==0 and target['username'].upper() not in protected)
    @app.post('/admin/accounts/{account_id}/reset')
    async def reset_password(request:Request,account_id:int):
        actor=current(request,gm=True);await form(request);limited(request,'reset-password',20,3600,str(actor['id']))
        target=database.account(account_id)
        if not target:raise HTTPException(404,'账号不存在')
        if int(target['gmlevel'])!=0 or target['username'].upper() in protected:raise HTTPException(403,'只能重置普通玩家账号，不能重置管理员或服务账号')
        generated=f'{secrets.randbelow(1000000):06d}';s,v=auth.credentials(target['username'],generated)
        if not database.set_password(account_id,s,v,ordinary_only=True,expected_v=target['v']):raise HTTPException(409,'目标账号信息已变化，重置未执行')
        return page(request,'account.html',target=public(target),characters=database.characters(account_id),can_reset=True,reset_password=generated)
    @app.get('/admin/settings')
    def settings_page(request:Request):
        current(request,gm=True)
        try:result=controller.request({'action':'get_config'})
        except ControlError as e:return page(request,'error.html',503,message=str(e))
        return page(request,'settings.html',values=result.get('settings',{}))
    @app.post('/admin/settings')
    async def apply_settings(request:Request):
        actor=current(request,gm=True);data=await form(request);limited(request,'settings',30,600,str(actor['id']))
        try:
            values={k.removeprefix('cfg__'):v for k,v in data.items() if k!='csrf'}
            if any(not k.startswith('cfg__') for k in data if k!='csrf'):raise ValueError('设置表单包含未知字段')
            before=controller.request({'action':'get_config'}).get('settings',{})
            checked=validate(values,int(before.get('MaxPlayerLevel',60)))
            changed={k:v for k,v in checked.items() if v!=before.get(k)}
            if not changed:return page(request,'settings.html',values=before,notice='设置没有变化')
            result=controller.request({'action':'apply_config','values':changed,'actor':actor['username']})
            return page(request,'settings.html',values=result.get('settings',{**before,**changed}),notice='设置已提交并热更新；出生等级和初始金钱仅影响新角色。')
        except (ValueError,ControlError) as e:
            return page(request,'settings.html',400,values=locals().get('before',{}),error=str(e))
    return app

app=create_app()
