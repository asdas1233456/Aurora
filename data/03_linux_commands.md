# Linux 常用命令与测试排障经验

本文整理测试工作中常用的 Linux 命令，重点面向日志排查、服务状态检查、文件操作和环境定位。

## 1. 文件与目录操作

### 查看当前目录

```bash
pwd
ls
ls -l
ls -la
```

经验：

- `ls -la` 常用于排查隐藏文件，例如 `.env`、`.gitignore`、日志目录
- 测试环境排查时，先确认当前路径是否正确，避免误操作

### 切换目录

```bash
cd /path/to/dir
cd ..
cd ~
```

### 创建目录

```bash
mkdir test_dir
mkdir -p logs/app
```

### 删除文件或目录

```bash
rm file.txt
rm -rf temp_dir
```

经验：

- `rm -rf` 风险很高，线上环境要特别谨慎
- 测试环境建议先 `ls` 确认后再删

## 2. 文件内容查看

### 查看文件头部和尾部

```bash
head -n 20 app.log
tail -n 50 app.log
tail -f app.log
```

经验：

- `tail -f` 是看实时日志最常用的命令
- 线上问题复现时，可边操作边盯日志输出

### 分页查看

```bash
less app.log
more app.log
```

### 搜索关键字

```bash
grep "ERROR" app.log
grep -n "Exception" app.log
grep -i "timeout" app.log
grep -r "关键字" /path/to/dir
```

经验：

- `-n` 可以显示行号，便于定位
- `-i` 忽略大小写，适合搜索 error、warn、fail 等关键词

## 3. 进程与端口检查

### 查看进程

```bash
ps -ef
ps -ef | grep java
ps -ef | grep python
```

### 查看端口占用

```bash
netstat -ano | grep 8080
ss -lntp
```

### 杀掉进程

```bash
kill 1234
kill -9 1234
```

经验：

- `kill -9` 虽然直接，但不适合当常规手段
- 优先定位为什么进程没有正常退出

## 4. 系统资源查看

### 查看 CPU 和内存

```bash
top
htop
free -h
vmstat 1
```

### 查看磁盘空间

```bash
df -h
du -sh *
```

经验：

- 系统变慢时，先看 CPU、内存、磁盘是否异常
- 很多“服务突然不可用”的根因，其实是磁盘满了

## 5. 网络排查

### 测试连通性

```bash
ping 127.0.0.1
ping 域名
```

### 测试端口

```bash
telnet 主机 端口
nc -zv 主机 端口
```

### 发起 HTTP 请求

```bash
curl http://example.com
curl -I http://example.com
curl -X POST http://example.com/api
```

经验：

- 接口不通时，先分层判断：
  - DNS 是否正常
  - 端口是否通
  - 服务是否启动
  - 反向代理是否配置正确

## 6. 权限与用户

### 查看权限

```bash
ls -l
```

### 修改权限

```bash
chmod 755 script.sh
chmod +x run.sh
```

### 切换用户

```bash
su 用户名
sudo 命令
```

经验：

- 脚本执行失败时，先看是否有执行权限
- 日志写不进去时，往往是目录权限问题

## 7. 压缩与传输

### 打包与解压

```bash
tar -czvf logs.tar.gz logs/
tar -xzvf logs.tar.gz
zip -r report.zip report/
unzip report.zip
```

### 远程复制

```bash
scp file.txt user@host:/tmp/
scp user@host:/tmp/app.log ./
```

## 8. 测试中的常见使用场景

### 场景 1：接口报错

排查顺序：

- `curl` 看接口是否可访问
- `ps -ef` 看进程是否在
- `netstat` 或 `ss` 看端口是否监听
- `tail -f` 看应用日志

### 场景 2：页面打不开

排查顺序：

- `ping` 看域名是否能解析
- `curl -I` 看 HTTP 响应
- 查看网关、Nginx、应用日志

### 场景 3：性能变差

排查顺序：

- `top` 看 CPU
- `free -h` 看内存
- `df -h` 看磁盘
- `vmstat` 看系统负载

## 9. 测试建议

- 命令不是目的，定位问题才是目的
- 建议把常用排查命令按场景整理成手册
- 每次线上问题排查后，补充到知识库里
