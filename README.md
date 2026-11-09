# realm-admin

WoW 1.12.1 / vMaNGOS 账号与世界参数管理网页。FastAPI + Jinja2，原创网页资源；不包含游戏素材、运行数据库或生产凭据。源码从现有部署导出：网页和控制助手 Python 源码已核对与运行主机一致；公开版调整了路径默认值、配置示例和镜像源码构建方式。

## 当前功能与边界

- 注册、登录、查看自己角色、修改密码。
- GM 查看账号与角色，向普通账号重置随机六位密码。
- 经 Unix socket 控制助手调整九项允许热更的服务端参数。
- 不包含世界机器人人数配置、邮件赠送装备等后续设想的网页功能。
- 使用现有 realmd/characters 表，不创建数据库或修改表结构；需要服务端已有 `account_access` 权限模型。
- 控制助手使用 Linux `SO_PEERCRED`；该部署示例仅适用于 Linux Docker host 网络，不承诺 Windows/macOS 原生助手支持。

## 配置与容器启动

本仓库暂为源码构建候选，尚未发布镜像。整套游戏部署入口由 `realm` 项目维护。

1. 将 `.env.example` 复制为 `.env`，填写专用数据库账号、密码及随机至少32字符的签名密钥。
2. 依照 [权限说明](web/README.md#mysql列权限) 由数据库管理员授予最小列权限；网页账号不得拥有DDL权限。
3. 准备 `secrets/soap.json`，内容形如 `{"username":"YOUR_SERVICE_ACCOUNT","password":"YOUR_SERVICE_PASSWORD"}`。该账号须获准调用 `reload config`。文件不要提交到Git。
4. 将现有世界服务使用的真实配置目录挂载到 compose 的 `/etc/vmangos`。示例中的 `./server-config` 必须改为真实共享目录，不能只复制一份不会被游戏使用的配置；助手用原子替换写入，必须挂载目录。
5. 创建 `run/control`、`backups` 目录；控制助手需要写入socket与备份目录。网页uid10001需要遍历并连接socket目录。
6. 启动：`docker compose -f compose.example.yaml up -d --build`。

示例网页仅绑定 `127.0.0.1:18086`；生产使用HTTPS反向代理并设 `COOKIE_SECURE=1`。保持单worker，限流与会话附加状态在内存中。MySQL和SOAP需在容器host网络可达的地址监听；SOAP当前使用固定 `127.0.0.1:7878`。勿将SOAP开放给公网。

`/healthz` 只代表网页进程存活，不代表数据库、控制助手或游戏世界健康。

## 开发与验证

```sh
cd web
uv sync --group dev --frozen
uv run pytest -q
```

现有单测使用 FakeDB/模拟socket，不能替代真实数据库、SOAP热更、浏览器和多架构容器验收。新公开 Dockerfile 从源码构建，不包含开发机 wheelhouse；本次是否完成镜像构建见发布记录。

## 来源与授权

自研网页、控制助手及测试来自现有 wow-gm-control 工作目录。未发现该目录明确的项目级 LICENSE，当前导入不擅自追加许可证；公开前需项目所有者确认开源授权。第三方Python依赖保留各自许可证。
