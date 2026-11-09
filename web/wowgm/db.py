import os
import pymysql

# AccountMgr::GetSecurity uses account_access, not the legacy account.gmlevel.
# Resolve global (-1) and current-realm grants in every account query.
EFFECTIVE_ROLE = "COALESCE((SELECT MAX(access.gmlevel) FROM realmd.account_access access WHERE access.id=a.id AND access.RealmID IN (-1,%s)),0) AS gmlevel"
PRIVATE_COLUMNS = "a.id,a.username," + EFFECTIVE_ROLE + ",a.v,a.s,a.joindate,a.last_login,a.online"
PUBLIC_COLUMNS = "a.id,a.username," + EFFECTIVE_ROLE + ",a.joindate,a.last_login,a.online"

class GameDB:
    @property
    def realm_id(self):
        return int(os.getenv("REALM_ID", "1"))
    def connection(self):
        return pymysql.connect(host=os.getenv("MYSQL_HOST", "127.0.0.1"), port=int(os.getenv("MYSQL_PORT", "13306")),
            user=os.getenv("MYSQL_USER", "wowweb"), password=os.environ.get("MYSQL_PASSWORD", ""),
            charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor, autocommit=True,
            connect_timeout=5, read_timeout=8, write_timeout=8)
    def one(self, sql, params):
        with self.connection() as db, db.cursor() as c:
            c.execute(sql, params)
            return c.fetchone()
    def account(self, account_id):
        return self.one(f"SELECT {PRIVATE_COLUMNS} FROM realmd.account a WHERE a.id=%s", (self.realm_id,account_id))
    def find(self, name):
        return self.one(f"SELECT {PRIVATE_COLUMNS} FROM realmd.account a WHERE a.username=%s", (self.realm_id,name))
    def register(self, name, s, v):
        try:
            with self.connection() as db, db.cursor() as c:
                # No access row is inserted: effective role is 0 without a grant.
                c.execute("INSERT INTO realmd.account (username,s,v) VALUES (%s,%s,%s)", (name,s,v))
                return c.lastrowid
        except pymysql.IntegrityError:
            raise ValueError("该账号不可用，请换一个名称") from None
    def set_password(self, account_id, s, v, ordinary_only=False, expected_v=None):
        sql = "UPDATE realmd.account a SET a.s=%s,a.v=%s WHERE a.id=%s"
        params = [s,v,account_id]
        if ordinary_only:
            # Re-check role atomically with the write, including global grants.
            sql += " AND NOT EXISTS (SELECT 1 FROM realmd.account_access access WHERE access.id=a.id AND access.RealmID IN (-1,%s) AND access.gmlevel>0)"
            params.append(self.realm_id)
        if expected_v is not None:
            sql += " AND a.v=%s"
            params.append(expected_v)
        with self.connection() as db, db.cursor() as c:
            c.execute(sql, tuple(params))
            return c.rowcount == 1
    def accounts(self, query=""):
        with self.connection() as db, db.cursor() as c:
            c.execute(f"SELECT {PUBLIC_COLUMNS} FROM realmd.account a WHERE a.username LIKE %s ORDER BY a.id DESC LIMIT 200", (self.realm_id,"%"+query+"%"))
            return c.fetchall()
    def characters(self, account_id):
        with self.connection() as db, db.cursor() as c:
            c.execute("SELECT guid,account,name,race,class,level,online,map,zone,money FROM characters.characters WHERE account=%s ORDER BY level DESC,name LIMIT 100", (account_id,))
            return c.fetchall()
