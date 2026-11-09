# 艾泽拉斯 · 账号与世界规则控制台

FastAPI + Jinja2 + 原生 CSS，原创暗石质、金属框、金色标题、暗红按钮和羊皮纸卡片。无外部 CDN、JavaScript 框架或从 MPQ 提取的网页图片。只操作现有游戏账号字段，不增加数据库、表、字段或索引；不使用 SQLite，不保存操作审计。

## 运行

```bash
uv sync --group dev
# 按下文配置环境变量；SECRET_KEY 至少32个随机字符
uv run uvicorn wowgm.app:app --host 127.0.0.1 --port 18086 --workers 1
```

账号管理连接现有 vMaNGOS MySQL；世界参数操作经本机 Unix socket 控制助手，不直接写配置或重启游戏服务。无数据库连接时也能打开登录页，但实际登录和注册需要数据库。

## 环境变量

| 名称 | 默认值/要求 |
|---|---|
| `MYSQL_HOST` / `MYSQL_PORT` | `127.0.0.1` / `13306` |
| `REALM_ID` | `1`；与当前游戏世界RealmID一致 |
| `MYSQL_USER` / `MYSQL_PASSWORD` | 专用数据库用户和密码；不得使用root |
| `SECRET_KEY` | 推荐通过环境变量提供，至少32字符，重启保持不变 |
| `DATA_DIR` | 仅在没提供SECRET_KEY时保存自动生成的签名密钥；默认 `.local-data`，不存数据库或会话表 |
| `CONTROL_SOCKET` | `/run/wow-gm/control.sock` |
| `COOKIE_SECURE` | `0`，局域网HTTP；部署HTTPS时设 `1` |
| `PROTECTED_ACCOUNTS` | 逗号分隔的服务账号保护名单，默认 `__WEB_SERVICE,GMUI_SERVICE`；部署时补齐实际服务账号 |
| `BIND_HOST` / `PORT` | Docker入口默认 `127.0.0.1` / `18086` |

只能用 **1个worker**：限流保存在进程内存，重启清空，符合本地测试用途。签名cookie最长8小时，HttpOnly、SameSite=Lax；包含账号ID、随机CSRF值和由账号当前盐/校验值派生的HMAC指纹，不包含密码或原始盐/校验值。每请求从MySQL重读有效账号权限和凭据指纹。有效权限按现有 `account_access` 表中 `RealmID IN (-1, REALM_ID)` 的最大 `gmlevel` 计算，没记录就是0；不回退到已不被本部署游戏使用的 `account.gmlevel` 旧字段。改密码或GM重置后旧网页cookie自然失效。不调用游戏登录、不修改游戏sessionkey、不会因网页登录踢掉游戏角色。

所有变更需要CSRF校验；登录、注册和密码操作有内存限流。新账号的INSERT不包含权限字段，也不新增 `account_access` 行，因此有效权限为0；注册不能指定权限。普通用户只能访问自己角色；GM请求必须当前有效gmlevel>=6。GM重置仅接受当前有效gmlevel=0且不在服务账号保护名单中的目标，生成随机6位数字密码，仅直接POST响应展示一次，不存cookie、文件或日志；后续GET不再显示。用户仍可自行用浏览器保存当前页面，因此“只显示一次”指服务端不提供再次获取功能。

## MySQL列权限

只需现有对象的以下权限，不需要执行schema迁移：

- `realmd.account`：SELECT列 `id,username,v,s,joindate,last_login,online`
- `realmd.account_access`：SELECT列 `id,gmlevel,RealmID`，仅查询既有权限，不写权限
- `realmd.account`：INSERT列 `username,v,s`
- `realmd.account`：UPDATE列 `v,s`
- `characters.characters`：SELECT列 `guid,account,name,race,class,level,online,map,zone,money`

不授予UPDATE gmlevel/sessionkey/online，也不授予任何游戏DDL权限。注册不写 `realmcharacters`，realmd对不存在的计数行按0角色返回，角色创建由游戏原生逻辑处理。所有输入SQL值均参数化。普通玩家密码重置的UPDATE中同时包含 `NOT EXISTS` 当前世界/全局非零权限行的条件及旧verifier的CAS条件，防止权限变化后误重置GM账号。权限来源与本部署 [AccountMgr.cpp](https://github.com/vmangos/core/blob/9b7fb4dfdb1d863ef93c5cf24d57aff92124f41f/src/game/AccountMgr.cpp#L547) 一致。

## 控制助手协议

每次请求新建一个Unix流socket连接，UTF-8 JSON对象加换行。最多接收64KiB，超时10秒；响应可以换行或连接EOF结束。示例：

```json
{"action":"get_config"}
{"ok":true,"settings":{"Rate.Health":1,"MaxPlayerLevel":60}}
```

```json
{"action":"apply_config","values":{"Rate.Health":2},"actor":"PLAYER"}
{"ok":true,"settings":{"Rate.Health":2,"MaxPlayerLevel":60}}
```

错误响应：`{"ok":false,"error":"中文说明"}`。

`get_config`应返回全部9项设置及只读MaxPlayerLevel。网页只发送有变化的白名单值，actor取当前数据库账号名。白名单：

- `Rate.XP.Kill`、`Rate.XP.Quest`、`Rate.XP.Explore`
- `Rate.Health`、`Rate.Mana`、`Rate.Energy`
- `Rate.Drop.Money`
- `StartPlayerLevel`、`StartPlayerMoney`

倍率0.1–20；出生等级1–min(MaxPlayerLevel,60)且整数；初始金钱0–100000000铜币且整数。MaxPlayerLevel只读，不能通过POST修改。控制助手仍应独立进行白名单、范围、权限、备份和热更校验，不能只依赖网页。

## Docker示例

根目录 `compose.example.yaml`使用host网络，仅绑定指定LAN地址，以uid/gid10001非root运行，根文件系统只读、/tmp为tmpfs、丢弃capabilities。先准备自己的 `.env`（不要提交），再将data目录设为uid10001可写；若SECRET_KEY由ENV提供，该目录不存业务状态。socket父目录需可遍历、socket需允许gid10001连接，或配置额外group_add。只挂载socket目录，不给网页配置文件写权限。

示例包含控制助手，但不负责启动MySQL与游戏服务；需要预先配置现有服务。`/healthz`是网页进程存活检查，不代表数据库或游戏服务器健康。

## 验证

```bash
uv run pytest -q
```

单元测试覆盖SRP固定向量、注册权限、CSRF、身份与实时GM权限、6位重置和旧会话失效、服务账号保护、改密、9项白名单和数值范围、限流、socket协议和错误提示。测试使用FakeDB和SQL调用捕获，不等于真实MySQL执行验收；FakeDB分开建模legacy权限字段与account_access，包括全局授权、其他世界授权、不回退legacy、即时降权和重置原子权限条件。部署仍需以现有account_access真实权限行验收。

隔离FakeDB的Playwright检查已验证登录、查看页面、配置提交、390px移动端无横向溢出。截图未包含在公开仓库。真实部署仍需使用隔离游戏账号验证注册、离线密码认证、角色读取、GM权限、密码重置，以及控制助手热更新；不能用模拟结果代替。
