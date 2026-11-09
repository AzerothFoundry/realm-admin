import re
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from wowgm.app import create_app
from wowgm import auth
from wowgm.config import CONFIG,validate
from wowgm.control import ControlError

class FakeDB:
    def __init__(self):
        self.rows={};self.created=[];self.access=[(1,6,1)];self.realm_id=1
        for i,(name,role) in enumerate([('ADMIN',6),('PLAYER',0),('GMUI_SERVICE',0)],1):
            s,v=auth.credentials(name,'abc123')
            self.rows[i]={'id':i,'username':name,'gmlevel':role,'s':s,'v':v,'online':0,'joindate':'2026-10-31','last_login':None}
    def account(self,uid):
        row=deepcopy(self.rows.get(uid))
        if row is not None:row['gmlevel']=max((level for account,level,realm in self.access if account==uid and realm in (-1,self.realm_id)),default=0)
        return row
    def find(self,name):return next((self.account(a['id']) for a in self.rows.values() if a['username']==name),None)
    def register(self,name,s,v):
        if self.find(name):raise ValueError('该账号不可用，请换一个名称')
        uid=max(self.rows)+1;self.rows[uid]={'id':uid,'username':name,'gmlevel':0,'s':s,'v':v,'online':0,'joindate':'2026-10-31','last_login':None};self.created.append(uid);return uid
    def set_password(self,uid,s,v,ordinary_only=False,expected_v=None):
        a=self.rows.get(uid)
        if not a or (ordinary_only and self.account(uid)['gmlevel']!=0) or (expected_v is not None and expected_v!=a['v']):return False
        a.update(s=s,v=v);return True
    def accounts(self,query=''):return [self.account(a['id']) for a in self.rows.values() if query.upper() in a['username']]
    def characters(self,uid):return [{'guid':1,'account':uid,'name':'旅人','race':1,'class':1,'level':60,'online':0,'map':0,'zone':12,'money':12500}] if uid==2 else []

class FakeControl:
    def __init__(self):self.values={**{k:1 for k in CONFIG},'StartPlayerMoney':0,'MaxPlayerLevel':60};self.calls=[];self.fail=False
    def request(self,payload):
        self.calls.append(deepcopy(payload))
        if self.fail:raise ControlError('控制服务暂时不可用')
        if payload['action']=='apply_config':self.values.update(payload['values'])
        return {'ok':True,'settings':deepcopy(self.values)}

@pytest.fixture
def env():
    db=FakeDB();control=FakeControl();app=create_app(db,control,{'secret_key':'x'*48,'cookie_secure':False,'protected_accounts':'GMUI_SERVICE'})
    with TestClient(app) as client:yield client,db,control,app

def csrf(client,path='/login'):
    r=client.get(path);assert r.status_code==200
    return re.search(r'name="csrf" value="([^"]+)"',r.text).group(1)

def login(client,name='PLAYER',secret='abc123'):
    return client.post('/login',data={'csrf':csrf(client),'username':name,'password':secret})

def test_srp_known_vector():
    s,v=auth.credentials('player','123456',bytes(range(32)))
    assert s=='1F1E1D1C1B1A191817161514131211100F0E0D0C0B0A09080706050403020100'
    assert v=='424F400C65CC0CEF86A19F6F8180ED21E0264328369CA56595D3C587074D9338'
    assert auth.verify('PLAYER','123456',s,v)
    assert not auth.verify('PLAYER','654321',s,v)
    assert not auth.verify('OTHER','123456',s,v)
    assert auth.verify('player','aBc123',*auth.credentials('PLAYER','ABC123'))

@pytest.mark.parametrize('bad',['short','with space','密码123456','x'*17])
def test_password_rules(bad):
    with pytest.raises(ValueError):auth.password(bad)

def test_csrf_required_for_login_register(env):
    c,db,_,_=env
    assert c.post('/login',data={'username':'PLAYER','password':'abc123'}).status_code==403
    assert c.post('/register',data={'username':'NEW','password':'abc123'}).status_code==403
    assert not db.created

def test_register_normal_only(env):
    c,db,_,_=env
    data={'csrf':csrf(c,'/register'),'username':'new_player','password':'123456','confirm_password':'123456'}
    response=c.post('/register',data={**data,'gmlevel':'6'})
    assert response.status_code==400 and not db.created
    data['csrf']=csrf(c,'/register');response=c.post('/register',data=data)
    assert response.status_code==200
    row=db.find('NEW_PLAYER');assert row['gmlevel']==0
    assert auth.verify('NEW_PLAYER','123456',row['s'],row['v'])
    assert row['s'] not in response.text and row['v'] not in response.text

def test_offline_login_and_cookie(env):
    c,db,_,_=env;r=login(c)
    assert r.status_code==200 and '旅人' in r.text
    assert db.rows[2]['online']==0
    assert 'httponly' in r.headers['set-cookie'].lower()
    assert 'samesite=lax' in r.headers['set-cookie'].lower()
    assert 'no-store' in r.headers['cache-control']
    assert db.rows[2]['v'] not in r.text and db.rows[2]['s'] not in r.text

def test_normal_cannot_admin(env):
    c,_,control,_=env;login(c)
    assert c.get('/admin/accounts').status_code==403
    assert c.get('/admin/accounts/1').status_code==403
    assert c.get('/admin/settings').status_code==403
    assert c.post('/admin/accounts/1/reset',data={'csrf':csrf(c,'/me')}).status_code==403
    assert not control.calls

def test_gmlevel_rechecked_on_every_request(env):
    c,db,_,_=env;login(c,'ADMIN');assert c.get('/admin/accounts').status_code==200
    db.access=[]
    assert db.rows[1]['gmlevel']==6  # legacy value cannot grant web access
    assert c.get('/admin/accounts').status_code==403

def test_reset_six_digits_once_and_old_session_invalidated(env):
    c,db,_,app=env;login(c,'ADMIN')
    with TestClient(app) as player:
        login(player)
        token=csrf(c,'/admin/accounts/2')
        r=c.post('/admin/accounts/2/reset',data={'csrf':token})
        assert r.status_code==200
        password=re.search(r'<code>(\d{6})</code>',r.text).group(1)
        assert auth.verify('PLAYER',password,db.rows[2]['s'],db.rows[2]['v'])
        assert password not in c.get('/admin/accounts/2').text
        assert player.get('/me',follow_redirects=False).status_code==303
        assert db.rows[2]['gmlevel']==0

def test_reset_protected_and_gm_rejected(env):
    c,_,_,_=env;login(c,'ADMIN')
    token=csrf(c,'/admin/accounts/2')
    assert c.post('/admin/accounts/1/reset',data={'csrf':token}).status_code==403
    assert c.post('/admin/accounts/3/reset',data={'csrf':token}).status_code==403

def test_reset_and_change_require_csrf(env):
    c,_,_,_=env;login(c,'ADMIN')
    assert c.post('/admin/accounts/2/reset',data={'csrf':'wrong'}).status_code==403
    assert c.post('/me/password',data={'csrf':'wrong'}).status_code==403

def test_own_password_change_preserves_character(env):
    c,db,_,_=env;login(c)
    r=c.post('/me/password',data={'csrf':csrf(c,'/me'),'current_password':'abc123','new_password':'654321','confirm_password':'654321'})
    assert r.status_code==200 and '旅人' in r.text
    assert auth.verify('PLAYER','654321',db.rows[2]['s'],db.rows[2]['v'])
    assert c.get('/me').status_code==200

def test_config_whitelist_and_actor(env):
    c,_,control,_=env;login(c,'ADMIN')
    token=csrf(c,'/admin/settings')
    r=c.post('/admin/settings',data={'csrf':token,'cfg__Rate.Health':'2.5'})
    assert r.status_code==200
    assert control.calls[-1]=={'action':'apply_config','values':{'Rate.Health':2.5},'actor':'ADMIN'}
    applied=sum(x['action']=='apply_config' for x in control.calls)
    for key,value in [('MaxPlayerLevel','100'),('Rate.Health','NaN'),('Rate.Mana','21'),('StartPlayerLevel','61'),('StartPlayerMoney','1.1')]:
        r=c.post('/admin/settings',data={'csrf':csrf(c,'/admin/settings'),'cfg__'+key:value})
        assert r.status_code==400
    assert sum(x['action']=='apply_config' for x in control.calls)==applied

def test_settings_no_unauthorized_or_csrf_apply(env):
    c,_,control,_=env;login(c)
    assert c.post('/admin/settings',data={'csrf':csrf(c,'/me'),'cfg__Rate.Health':'2'}).status_code==403
    assert not control.calls
    login(c,'ADMIN')
    assert c.post('/admin/settings',data={'csrf':'bad','cfg__Rate.Health':'2'}).status_code==403
    assert not control.calls

def test_login_rate_limit(env):
    c,_,_,_=env
    for _ in range(10):
        assert c.post('/login',data={'csrf':csrf(c),'username':'PLAYER','password':'wrongpass'}).status_code==400
    assert c.post('/login',data={'csrf':csrf(c),'username':'PLAYER','password':'abc123'}).status_code==429

def test_control_failure_is_clear(env):
    c,_,control,_=env;login(c,'ADMIN');control.fail=True
    r=c.get('/admin/settings');assert r.status_code==503 and '控制服务暂时不可用' in r.text

def test_limits():
    with pytest.raises(ValueError):validate({'StartPlayerLevel':40},maximum=30)
    with pytest.raises(ValueError):validate({'GameType':0})
    assert len(CONFIG)==9


def test_existing_short_game_password_can_login_but_new_password_policy_stays_six():
    salt=bytes(range(32))
    s=format(int.from_bytes(salt,"little"),"X")
    v=auth.verifier("LEGACY","a",salt)
    assert auth.verify("LEGACY","A",s,v)
    with pytest.raises(ValueError):auth.credentials("LEGACY","a")


def test_authoritative_access_not_legacy(env):
    c,db,_,_=env
    db.rows[1]['gmlevel']=0
    login(c,'ADMIN')
    assert c.get('/admin/accounts').status_code==200  # grant in account_access wins
    db.rows[2]['gmlevel']=6
    login(c,'PLAYER')
    assert c.get('/admin/accounts').status_code==403  # legacy column never grants access


def test_global_grant_and_other_realm_scope(env):
    c,db,_,_=env
    db.access=[(1,6,-1)]
    login(c,'ADMIN')
    assert c.get('/admin/accounts').status_code==200
    db.access=[(1,6,2)]
    assert c.get('/admin/accounts').status_code==403


def test_reset_access_grant_even_with_legacy_zero(env):
    c,db,_,_=env
    db.access.append((2,1,1));assert db.rows[2]['gmlevel']==0
    login(c,'ADMIN')
    token=csrf(c,'/admin/accounts/2')
    assert c.post('/admin/accounts/2/reset',data={'csrf':token}).status_code==403
