# 测试网站与练习资源

本文整理常见的软件测试练习网站，适合 API 测试、Web 自动化测试、接口联调和故障定位。

## 1. API 测试网站

### httpbin

- 地址：`https://httpbin.org/`
- 适用场景：
  - 验证请求头、请求方法、Query 参数、Body 是否正确
  - 验证重定向、状态码、鉴权、延迟响应
  - 调试客户端请求格式是否符合预期
- 常用接口：
  - `GET /get`
  - `POST /post`
  - `GET /status/200`
  - `GET /status/404`
  - `GET /delay/3`
  - `GET /headers`
- 实战经验：
  - 接口自动化脚本刚起步时，可以先对接 httpbin 验证基础请求能力
  - 如果请求明明发出去了，但服务端说参数不对，先看 `/anything` 或 `/post` 返回内容
  - 做超时测试时，`/delay/n` 非常适合验证重试机制、超时机制、熔断机制

### ReqRes

- 地址：`https://reqres.in/`
- 适用场景：
  - 模拟登录、用户列表、单对象查询、分页等常见接口场景
  - 演示 Postman、Playwright API、Python requests 的测试案例
- 测试重点：
  - 正常请求与异常请求
  - 鉴权 Header
  - 响应结构校验
  - 状态码断言
- 实战经验：
  - 适合教学和作品集展示，因为接口结构比较“业务化”
  - 注意有些数据是演示数据，不一定持久化

### JSONPlaceholder

- 地址：`https://jsonplaceholder.typicode.com/`
- 适用场景：
  - RESTful 风格接口练习
  - 假数据接口联调
  - 前后端联调演示
- 常见资源：
  - `/posts`
  - `/comments`
  - `/albums`
  - `/photos`
  - `/todos`
  - `/users`
- 实战经验：
  - 很适合练习分页、数据映射、对象解析、Schema 校验
  - 用于教学时，可以配合 Python、Java、Postman、JMeter 同时练习

## 2. Web 自动化练习网站

### The Internet

- 地址：`https://the-internet.herokuapp.com/`
- 适用场景：
  - 登录
  - 文件上传
  - iframe
  - JavaScript Alert
  - 动态加载
  - 拖拽
  - 多窗口
  - 下拉框
  - 状态码测试
- 实战经验：
  - 这是非常经典的 UI 自动化练习网站
  - 很适合练习元素等待、稳定定位、页面对象设计
  - “Dynamic Loading” 页面很适合训练同步等待能力

### Playwright TodoMVC Demo

- 地址：`https://demo.playwright.dev/todomvc/`
- 适用场景：
  - Web 自动化入门
  - 端到端测试示例
  - 待办事项增删改查
- 可练习点：
  - 输入框
  - 列表断言
  - 过滤器切换
  - 状态变更
- 实战经验：
  - 非常适合 Playwright、Selenium、Cypress 的入门示例
  - 页面简单，便于聚焦测试结构，而不是被业务流程干扰

### Test Pages

- 地址：`https://testpages.herokuapp.com/styled/`
- 适用场景：
  - 表单输入
  - DOM 操作
  - JavaScript 行为验证
  - 基础功能点覆盖
- 实战经验：
  - 适合补齐不同控件的定位与断言方式
  - 用于训练探索式测试也很合适

## 3. 测试网站选择建议

### 什么时候用 API 模拟网站

- 当你要练习接口自动化脚本时
- 当你要排查请求参数或响应结构时
- 当你还没有真实后端环境时

### 什么时候用 Web 练习网站

- 当你要练习 UI 自动化时
- 当你要验证等待、定位、断言、流程编排时
- 当你要写作品集案例时

## 4. 使用测试网站的经验总结

### 建议做法

- 先把网站当成“练习场”，不要一上来就追求复杂框架
- 每个网站挑 3 到 5 个稳定场景先打通
- 先写手工测试点，再写自动化脚本
- 每个场景至少覆盖：
  - 正常路径
  - 异常路径
  - 边界输入

### 常见误区

- 只会写 happy path，不测异常路径
- 只看页面结果，不检查网络请求和日志
- 自动化脚本能跑就算完，没有做可维护性设计
- 把测试网站当生产网站使用，忽略其演示性质

## 5. 可扩展方向

- 基于这些网站编写 Postman 集合
- 基于这些网站编写 Pytest 自动化脚本
- 基于这些网站编写 Selenium / Playwright 案例
- 基于这些网站做接口压测与异常测试演示
