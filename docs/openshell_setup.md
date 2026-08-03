# OpenShell（NemoClaw 安全栈）部署配方 — local AI host/GB10 实测

工具执行的安全层：沙箱内**网络默认拒绝**，`policy update/set` 审批后放行（域名 × 发起进程双维授权）。
实证：未审批域名连接层阻断；审批 `h5.ele.me:443` + `binaries: /usr/bin/curl` 后 200；github 仍 BLOCKED。

## 安装（全部无 root）

```bash
pip install --user --break-system-packages uv && uv tool install openshell   # CLI 0.0.86, aarch64 ✓
# supervisor 二进制
docker pull ghcr.io/nvidia/openshell/supervisor:latest   # ghcr IPv6 抖动就 until 重试
docker create --name t ghcr.io/nvidia/openshell/supervisor:latest
mkdir -p ~/openshell/supervisor && docker cp t:/openshell-sandbox ~/openshell/supervisor/ && docker rm t
# JWT（docker 驱动强制）
mkdir -p ~/openshell/jwt ~/openshell/db ~/openshell/cfg && chmod 777 ~/openshell/db
openssl genpkey -algorithm ed25519 -out ~/openshell/jwt/signing.pem
openssl pkey -in ~/openshell/jwt/signing.pem -pubout -out ~/openshell/jwt/public.pem
echo -n local-1 > ~/openshell/jwt/kid; chmod 644 ~/openshell/jwt/*
```

`~/openshell/cfg/gateway.toml`：`[openshell] version=1` 头必须有；gateway_jwt 三个 path 指 /etc/openshell/jwt；
`allow_unauthenticated_users = true`（仅本机单人）。

## 网关容器（关键坑全在参数里）

```bash
docker run -d --name openshell-gateway --restart unless-stopped \
  --group-add $(stat -c %g /var/run/docker.sock) --network host \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v ~/openshell/supervisor/openshell-sandbox:$HOME/openshell/supervisor/openshell-sandbox:ro \
  -v ~/openshell/db:$HOME/openshell/db \
  -v ~/openshell/jwt:/etc/openshell/jwt:ro \
  -v ~/openshell/cfg/gateway.toml:/etc/openshell/gateway.toml:ro \
  -e HOME=$HOME/openshell/db -e OPENSHELL_GATEWAY_CONFIG=/etc/openshell/gateway.toml \
  -e OPENSHELL_DRIVERS=docker \
  -e OPENSHELL_DOCKER_SUPERVISOR_BIN=$HOME/openshell/supervisor/openshell-sandbox \
  -e OPENSHELL_DB_URL=sqlite:$HOME/openshell/db/openshell.db -e OPENSHELL_DISABLE_TLS=true \
  ghcr.io/nvidia/openshell/gateway:latest --bind-address 0.0.0.0 --port 18080
openshell gateway add http://127.0.0.1:18080 --local --name local && openshell gateway select local
```

坑位对照：镜像 CMD `--port 8080` 会**覆盖 TOML**（必须命令行给 18080，8080/8081 被 Step/kitten 占用）；
HOME 挂载必须**容器内外同路径**（supervisor 缓存 bind-mount 由宿主 dockerd 解析）；host network 让
沙箱经 `host.openshell.internal`（=沙箱网桥宿主侧 IP）回连网关。

## 沙箱与审批

```bash
openshell sandbox create --name cat-tools --from base
openshell sandbox exec -- sh -c "curl -m 8 https://h5.ele.me/"   # 默认拒绝 → 000
openshell policy update cat-tools --add-endpoint h5.ele.me:443   # 审批（第一维：域名）
# 第二维：发起进程。用 policy set 提交 YAML，在规则里加：
#   endpoints: [- host: h5.ele.me, port: 443, tls: skip]
#   binaries:  [- path: /usr/bin/curl]
openshell sandbox get cat-tools --policy-only > pol.yaml  # 取当前 YAML 编辑后：
openshell policy set cat-tools --policy pol.yaml --wait
# 审计证据：docker logs <sandbox容器> 里的 OCSF NET:OPEN DENIED/ALLOWED 结构化日志
```

演示叙事：确认后的外卖深链域名逐一走审批；OCSF 审计日志就是"External action: approved by user"的证据画面。
