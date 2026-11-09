from wowgm.db import GameDB

class Cursor:
    rowcount=1
    lastrowid=4
    def __init__(self,calls):self.calls=calls
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute(self,sql,params):self.calls.append((sql,params))
    def fetchone(self):return {'id':1}
    def fetchall(self):return []

class Connection:
    def __init__(self,calls):self.calls=calls
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def cursor(self):return Cursor(self.calls)

def test_queries_resolve_access_with_parameterized_realm(monkeypatch):
    monkeypatch.setenv('REALM_ID','7')
    calls=[];db=GameDB();monkeypatch.setattr(db,'connection',lambda:Connection(calls))
    db.account(12);db.find('PLAYER');db.accounts('P')
    assert [params for _,params in calls]==[(7,12),(7,'PLAYER'),(7,'%P%')]
    for sql,_ in calls:
        assert 'MAX(access.gmlevel)' in sql
        assert 'access.RealmID IN (-1,%s)' in sql
        assert 'COALESCE' in sql
        assert 'a.gmlevel' not in sql

def test_reset_atomic_access_guard_keeps_cas(monkeypatch):
    monkeypatch.setenv('REALM_ID','1')
    calls=[];db=GameDB();monkeypatch.setattr(db,'connection',lambda:Connection(calls))
    assert db.set_password(12,'new-salt','new-verifier',ordinary_only=True,expected_v='old-verifier')
    sql,params=calls[-1]
    assert 'NOT EXISTS' in sql and 'realmd.account_access' in sql
    assert 'access.gmlevel>0' in sql and 'access.RealmID IN (-1,%s)' in sql
    assert 'a.gmlevel' not in sql and 'AND a.v=%s' in sql
    assert params==('new-salt','new-verifier',12,1,'old-verifier')
