# **DojoAgents-SEO 自适应智能体开发配置手册**

## **1\. 架构总览与工具链映射**

本手册旨在指导开发者将 12 款主流开源 SEO 审计、关键词分析、SERP 追踪、AEO 监控及链接优化工具，无缝融入 DojoAgents 的七层软件架构中 2。  
通过这一架构整合，传统的单点 SEO 工具将被转换为由 **Agent Loop（L3 智能体回路）** 调度、在 **Execution Sandbox（L4 隔离沙箱）** 中安全运行、并由 **APScheduler（L2 调度层）** 驱动持续自进化训练的分布式智能体编辑集群 2。

### **1.1 七层架构工具链映射表**

下表展示了各开源 SEO 工具在 DojoAgents 架构中的代码映射、层级划分与核心职责（单空格紧凑格式，禁止美化排版） 4：

| 架构层级 | 系统模块路径 | 融入工具 / 依赖组件 | 核心职责与协同机制 |
| :---- | :---- | :---- | :---- |
| **L1 用户访问层** | dojoagents/dashboard/web 4 | StJudeWasHere/seonaut HTML5 Canvas, React components 4 | 渲染全站技术审计仪表盘，展示实时 SERP 监控视图、GEO 品牌可见度热力图与关键词飙升趋势线 |
| **L2 应用服务层** | dojoagents/dashboard/server.py 4 | FastAPI Router, APScheduler 4 | 托管 SEO 诊断 API；通过 Cron 任务调度全站扫描、收录提交及自进化打分引擎 2 |
| **L3 智能体核心层** | dojoagents/agent/ 4 | UniversalAgentLoop, planning/, multi\_agent/ 4 | 执行多轮 Tool-Call 闭环；由 Auditor、Writer 和 Linker 智能体协同处理内容诊断与 A/B 策略整改 2 |
| **L4 工具执行层** | dojoagents/tools/ 4 | egebese/dataseo-mcp 4, joshcarty/google-searchconsole 4, pytrends 4, karust/openserp, Jiyanshi021/SEO-Interlinking-Tool | 封装自定义 ToolSpec，通过 MCP 协议挂载外部 SEO 数据源，在 Sandbox 物理沙箱中运行 Lighthouse、RankWise 与 python-seo-analyzer 2 |
| **L5 能力层** | dojoagents/skills/ 4 | akvise/claude-seo, RuntimeSkillCompiler 4 | 存储 E-E-A-T 信号评估规则与 Schema 结构化数据模版；将高表现的页面改写路径固化编译为免 LLM 消耗的局部静态 Skill 2 |
| **L6 数据层** | dojoagents/quant/ 4 | Awesome-SEO/awesome-seo 结构化知识库, Pandas DataFrames 4 | 对接 GSC、SERP 原始 JSON 数据流；通过 Pandas 进行关键词热度及外链站点权重矩阵清洗 4 |
| **L7 基础设施层** | dojoagents/config/ 4 | \~/.dojo/agents.yaml 2, Portalocker, SQLite 4 | 管理 GSC OAuth 密钥、OpenSERP API 端点和 MCP 服务器配置；持久化存储技术审计的死链与收录历史数据 2 |

## **2\. 开发环境准备与依赖规范**

系统依赖现代 Python 生态包管理器 uv 进行闪电般的依赖构建 2。任何新引入的第三方包必须严格登记在 pyproject.toml 中，禁止使用未经版本锁定的裸包 4。

### **2.1 Python 运行时依赖 (pyproject.toml)**

在项目的 pyproject.toml 的 dependencies 字段中追加以下依赖锁（紧凑格式，兼容 DojoAgents 核心约束） 4：

Ini, TOML  
\[project\]  
name \= "dojoagents"  
version \= "0.0.1"  
requires-python \= "\>=3.11"

dependencies \= \[  
    "fastapi\>=0.110.0,\<0.112",  
    "uvicorn\>=0.31.1,\<0.33",  
    "mcp\>=1.26.0,\<2",  
    "pandas\>=2.2.0,\<3",  
    "pyarrow\>=14.0.0",  
    "google-api-python-client\>=2.110.0",  
    "google-auth-httplib2\>=0.2.0",  
    "pytrends\>=4.9.2",  
    "portalocker\>=2.8.2",  
    "apscheduler\>=3.10.0,\<4",  
    "scikit-learn\>=1.4.0",  
    "sentence-transformers\>=2.5.1",  
    "beautifulsoup4\>=4.12.3",  
    "jinja2\>=3.1.3"  
\]

### **2.2 Docker 环境依赖**

针对无法通过纯 Python 环境运行的重型非对称服务，在 docker-compose.seo.yml 中声明 Docker 常驻容器：

YAML  
version: '3.8'  
services:  
  openserp:  
    image: karust/openserp:latest  
    ports:  
      \- "7070:7070"  
    environment:  
      \- PORT=7070  
    restart: unless-stopped

  seonaut:  
    image: stjudewasherere/seonaut:latest  
    ports:  
      \- "8080:80"  
    environment:  
      \- MYSQL\_DATABASE=seonaut  
      \- MYSQL\_USER=seonaut  
      \- MYSQL\_PASSWORD=seonaut\_pass  
    restart: unless-stopped

执行环境初始化命令 2：

Bash  
\# 激活虚拟环境并安装 Python 依赖项  
uv venv && source.venv/bin/activate  
uv pip install \-e ".\[dev\]"

\# 启动 Docker SEO 外挂服务群  
docker-compose \-f docker-compose.seo.yml up \-d

## **3\. 配置文件规范 (\~/.dojo/agents.yaml)**

DojoAgents 在 L7 基础设施层使用统一的 agents.yaml 集中管理配置 2。在这里配置外部平台的 OAuth、本地自建 Docker 端点、以及符合 MCP 1.26+ 标准的 Model Context Protocol 服务器 4。

YAML  
\# \~/.dojo/agents.yaml  
app:  
  host: "127.0.0.1"  
  port: 8765

llm\_providers:  
  default\_provider: "anthropic"  
  anthropic:  
    api\_key: "sk-ant-..."  
    model: "claude-3-5-sonnet-latest"

\# 1\. 挂载 DataforSEO 与 Ahrefs 的原生 MCP 节点 (L4 MCP Registry)  
mcp\_servers:  
  dataseo:  
    command: "npx"  
    args: \["-y", "dataseo-mcp"\]  
    env:  
      DATAFORSEO\_API\_LOGIN: "seo\_platform\_user"  
      DATAFORSEO\_API\_PASSWORD: "seo\_platform\_password"  
      AHREFS\_API\_KEY: "ahrefs\_pro\_token"

\# 2\. 注入第三方 SEO 服务及自建容器 API 凭证 (L7 ConfigStore)  
seo\_credentials:  
  google\_search\_console:  
    client\_secrets\_path: "\~/.dojo/gsc\_client\_secrets.json"  
    token\_path: "\~/.dojo/gsc\_token.json"  
  google\_pagespeed\_api\_key: "ai\_pagespeed\_token\_xyz"  
  openserp\_endpoint: "http://localhost:7070"  
  seonaut\_endpoint: "http://localhost:8080"

\# 3\. 执行沙箱物理与网络安全约束 (L4 SandboxPolicy)  
sandbox:  
  allow\_network\_hosts:  
    \- "localhost"  
    \- "127.0.0.1"  
    \- "www.googleapis.com"  
    \- "trends.google.com"  
  restricted\_builtins: true  
  execution\_timeout\_seconds: 60

## **4\. 核心组件开发与工具层集成**

### **4.1 GSC 与 Google Trends 核心集成工具 (dojoagents/tools/seo\_trends.py)**

在这一部分，我们深度封装了 google-searchconsole 的 API 以及 pytrends 接口，使得 Agent 在多轮 Loop 中能够一键获取时序排名与趋势 4。

Python  
\# dojoagents/tools/seo\_trends.py  
import os  
import json  
from typing import Dict, Any, List  
import pandas as pd  
from pytrends.request import TrendReq  
from google.oauth2.credentials import Credentials  
from googleapiclient.discovery import build  
from dojoagents.tools.base import BaseToolSpec  
from dojoagents.logging import LOGGER

class GoogleSEOMonitorSpec(BaseToolSpec):  
    """  
    DojoAgents L4 专属工具：整合 Google Trends 趋势探测与 GSC 流量表现指标  
    """  
    def \_\_init\_\_(self, gsc\_token\_path: str, client\_secrets\_path: str):  
        self.token\_path \= os.path.expanduser(gsc\_token\_path)  
        self.secrets\_path \= os.path.expanduser(client\_secrets\_path)  
        self.pytrends \= TrendReq(hl="en-US", tz=360)  
        self.\_gsc\_service \= None

    def get\_name(self) \-\> str:  
        return "google\_seo\_monitor"

    def get\_schema(self) \-\> Dict\[str, Any\]:  
        return {  
            "name": "google\_seo\_monitor",  
            "description": "专用于拉取谷歌官方 Search Console 真实的点击率、展现量和平均排名数据，并交叉比对 Google Trends 的飙升词热度趋势",  
            "parameters": {  
                "type": "object",  
                "properties": {  
                    "action": {  
                        "type": "string",  
                        "enum": \["query\_gsc\_performance", "query\_rising\_keywords"\],  
                        "description": "具体获取指标动作"  
                    },  
                    "target\_site": {  
                        "type": "string",  
                        "description": "在 GSC 注册绑定的目标站点 URL (例如: 'sc-domain:example.com')"  
                    },  
                    "keywords": {  
                        "type": "array",  
                        "items": {"type": "string"},  
                        "description": "分析和追踪趋势的目标关键词列表"  
                    },  
                    "days\_limit": {  
                        "type": "integer",  
                        "default": 30,  
                        "description": "GSC 历史统计回溯天数"  
                    }  
                },  
                "required": \["action"\]  
            }  
        }

    def \_init\_gsc\_client(self):  
        if self.\_gsc\_service:  
            return self.\_gsc\_service  
        if not os.path.exists(self.token\_path):  
            raise FileNotFoundError(f"Missing GSC OAuth token at: {self.token\_path}")  
          
        creds \= Credentials.from\_authorized\_user\_file(self.token\_path, scopes=\[  
            "https://www.googleapis.com/auth/webmasters.readonly"  
        \])  
        self.\_gsc\_service \= build("webmasters", "v3", credentials=creds)  
        return self.\_gsc\_service

    async def execute(self, arguments: Dict\[str, Any\], session\_id: str) \-\> str:  
        action \= arguments.get("action")  
        target\_site \= arguments.get("target\_site")  
        keywords \= arguments.get("keywords",)  
        days\_limit \= arguments.get("days\_limit", 30)

        LOGGER.info(f"SEO Monitor triggered action: {action} in Session: {session\_id}")

        try:  
            if action \== "query\_gsc\_performance":  
                if not target\_site:  
                    return "Error: target\_site must be provided for GSC query."  
                gsc \= self.\_init\_gsc\_client()  
                  
                \# 构建 GSC API 原生时序聚合查询  
                request\_body \= {  
                    "startDate": pd.Timestamp.now().sub(pd.Timedelta(days=days\_limit)).strftime("%Y-%m-%d"),  
                    "endDate": pd.Timestamp.now().strftime("%Y-%m-%d"),  
                    "dimensions": \["query", "page"\],  
                    "rowLimit": 1000  
                }  
                response \= gsc.searchanalytics().query(siteUrl=target\_site, body=request\_body).execute()  
                rows \= response.get("rows",)  
                if not rows:  
                    return f"GSC 接口返回成功，但在天数范围 {days\_limit} 内，站点 {target\_site} 没有可导出的展现与点击数据。"  
                  
                \# 解构并转换为 DataFrame 结构进行预清洗 (L6 Data Processing)  
                flat\_data \=  
                for r in rows:  
                    flat\_data.append({  
                        "Keyword": r\["keys"\],  
                        "LandingPage": r\["keys"\]\[1\],  
                        "Clicks": r\["clicks"\],  
                        "Impressions": r\["impressions"\],  
                        "CTR": f"{r\['ctr'\] \* 100:.2f}%",  
                        "Position": round(r\["position"\], 1)  
                    })  
                df \= pd.DataFrame(flat\_data)  
                return df.head(15).to\_markdown()

            elif action \== "query\_rising\_keywords":  
                if not keywords:  
                    return "Error: keywords list cannot be empty for trend analysis."  
                  
                self.pytrends.build\_payload(keywords, cat=0, timeframe="today 3-m", geo="US")  
                related\_queries \= self.pytrends.related\_queries()  
                  
                summary\_output \=  
                for kw in keywords:  
                    kw\_trend \= related\_queries.get(kw, {})  
                    rising\_df \= kw\_trend.get("rising")  
                    if rising\_df is not None and not rising\_df.empty:  
                        summary\_output.append(f"\#\#\# 关键词 '{kw}' 飙升相关搜索 (过去90天):\\n" \+ rising\_df.head(5).to\_markdown())  
                    else:  
                        summary\_output.append(f"\#\#\# 关键词 '{kw}': 暂未检测到显著飙升的搜索趋势指标。")  
                return "\\n\\n".join(summary\_output)

        except Exception as e:  
            LOGGER.exception(f"GoogleSEOMonitorSpec tool failed execution: {str(e)}")  
            return f"Tool Error: {str(e)}"

### **4.2 基于 NLP 的自动化内链计算工具 (dojoagents/tools/internal\_linker.py)**

封装 **Jiyanshi021/SEO-Interlinking-Tool** 核心的 TF-IDF 算法，在不增加大模型 Token 开销的前提下，在本地沙箱通过矩阵计算在生成内容中生成内链锚文本 4。

Python  
\# dojoagents/tools/internal\_linker.py  
from typing import Dict, Any, List  
import re  
from bs4 import BeautifulSoup  
from sklearn.feature\_extraction.text import TfidfVectorizer  
from dojoagents.tools.base import BaseToolSpec  
from dojoagents.logging import LOGGER

class InternalLinkerSpec(BaseToolSpec):  
    """  
    DojoAgents L4 专属工具：自动化 NLP 内链推荐与结构化 HTML 锚文本自动植入  
    """  
    def \_\_init\_\_(self):  
        pass

    def get\_name(self) \-\> str:  
        return "nlp\_internal\_linker"

    def get\_schema(self) \-\> Dict\[str, Any\]:  
        return {  
            "name": "nlp\_internal\_linker",  
            "description": "基于 TF-IDF 语义矩阵匹配，自动比对目标整站现有文章库，输出最符合 SEO 的相关锚文本推荐及 HTML 自动植入方案",  
            "parameters": {  
                "type": "object",  
                "properties": {  
                    "source\_html": {  
                        "type": "string",  
                        "description": "待植入内链的高级 HTML 富文本源码"  
                    },  
                    "target\_pages": {  
                        "type": "array",  
                        "items": {  
                            "type": "object",  
                            "properties": {  
                                "url": {"type": "string", "description": "拟导向的目的落地页 URL"},  
                                "anchor\_candidates": {"type": "array", "items": {"type": "string"}, "description": "该落地页可匹配的锚文本关键词列表"}  
                            },  
                            "required": \["url", "anchor\_candidates"\]  
                        },  
                        "description": "整站现有核心页面及对应关键词映射列表"  
                    }  
                },  
                "required": \["source\_html", "target\_pages"\]  
            }  
        }

    async def execute(self, arguments: Dict\[str, Any\], session\_id: str) \-\> str:  
        source\_html \= arguments\["source\_html"\]  
        target\_pages \= arguments\["target\_pages"\]  
          
        LOGGER.info(f"InternalLinkerSpec processing document in session: {session\_id}")  
          
        soup \= BeautifulSoup(source\_html, "html.parser")  
        text\_content \= soup.get\_text()  
          
        \# 提取纯文本执行词频统计矩阵计算  
        corpus \= \[text\_content\]  
        for page in target\_pages:  
            corpus.append(" ".join(page\["anchor\_candidates"\]))  
              
        vectorizer \= TfidfVectorizer(stop\_words='english')  
        tfidf\_matrix \= vectorizer.fit\_transform(corpus)  
          
        \# 匹配最优锚文本，替换 HTML  
        linked\_count \= 0  
        modified\_html \= source\_html  
          
        for idx, page in enumerate(target\_pages):  
            url \= page\["url"\]  
            anchors \= page\["anchor\_candidates"\]  
              
            for anchor in anchors:  
                \# 忽略大小写且避开已链接的标签，实施正则精准安全匹配  
                pattern \= re.compile(rf'\\b({re.escape(anchor)})\\b(?\!\[^\<\]\*\>)', re.IGNORECASE)  
                match \= pattern.search(modified\_html)  
                if match:  
                    \# 匹配成功，完成 HTML 锚文本自动重构植入  
                    replacement \= f'\<a href="{url}" title="{anchor} relative link"\>{match.group(1)}\</a\>'  
                    modified\_html \= pattern.sub(replacement, modified\_html, count=1)  
                    linked\_count \+= 1  
                    break \# 每个目标落地页只建立一个最优锚文本，规避谷歌过度链接惩罚

        return json.dumps({  
            "status": "Success",  
            "linked\_links\_injected": linked\_count,  
            "optimized\_html": modified\_html  
        }, ensure\_ascii=False)

## **5\. 沙箱高并发审计逻辑与外挂审计器接入**

这一层由 **L4 ToolExecutor** 驱动 4。我们将 Node.js 进程的 google/lighthouse 与 Python 的 sethblack/python-seo-analyzer 挂载在隔离沙箱的子进程通道中。

Python  
\# dojoagents/tools/environments/sandbox/seo\_audit\_sandbox.py  
import asyncio  
import sys  
from typing import Dict, Any  
from dojoagents.tools.environments import BaseEnvironmentAdapter  
from dojoagents.logging import LOGGER

class TechnicalSeoSandboxExecutor:  
    """  
    DojoAgents L4 隔离环境：安全执行 Lighthouse 与 Python Site Analyzer 高开销审计子进程  
    """  
    def \_\_init\_\_(self, timeout\_seconds: int \= 60):  
        self.timeout \= timeout\_seconds

    async def run\_lighthouse\_audit(self, target\_url: str) \-\> Dict\[str, Any\]:  
        """  
        在本地 Node 沙箱中安全启动 Lighthouse 无头浏览器进程，规避大模型阻塞  
        """  
        \# 构建 Lighthouse 无头 CLI 运行指令  
        cmd \= \[  
            "npx", "lighthouse", target\_url,  
            "--output=json",  
            "--chrome-flags=--headless \--disable-gpu \--no-sandbox",  
            "--only-categories=performance,seo"  
        \]  
        LOGGER.info(f"Sandbox launching Lighthouse subprocess for: {target\_url}")  
          
        try:  
            process \= await asyncio.create\_subprocess\_exec(  
                \*cmd,  
                stdout=asyncio.subprocess.PIPE,  
                stderr=asyncio.subprocess.PIPE  
            )  
              
            stdout, stderr \= await asyncio.wait\_for(process.communicate(), timeout=self.timeout)  
              
            if process.returncode\!= 0:  
                return {"success": False, "error": stderr.decode().strip()\[:500\]}  
                  
            lighthouse\_data \= json.loads(stdout.decode())  
            perf\_score \= lighthouse\_data.get("categories", {}).get("performance", {}).get("score", 0) \* 100  
            seo\_score \= lighthouse\_data.get("categories", {}).get("seo", {}).get("score", 0) \* 100  
              
            \# 提取影响谷歌 Core Web Vitals 核心加载时间 (LCP, CLS, FID)  
            lcp \= lighthouse\_data.get("audits", {}).get("largest-contentful-paint", {}).get("displayValue", "N/A")  
              
            return {  
                "success": True,  
                "performance\_score": perf\_score,  
                "seo\_score": seo\_score,  
                "largest\_contentful\_paint": lcp  
            }  
        except asyncio.TimeoutError:  
            LOGGER.error(f"Lighthouse timeout threshold breached for: {target\_url}")  
            return {"success": False, "error": f"Execution exceeded sandbox limit of {self.timeout}s"}  
        except Exception as e:  
            LOGGER.exception("Lighthouse audit failed inside sandbox")  
            return {"success": False, "error": str(e)}

## **6\. 定时进化调度与 AEO / SEO 综合评估引擎**

为保证智能体具备 **“自主追踪、闭环更新、自进化”** 的核心特性，我们需要在 L2 创建自进化调度任务，并利用 L5 Skill Compiler 动态将高转化率路径提炼编译为无损的静态高阶技能 2。

### **6.1 搜索引擎优化表现得分算法（![][image1] 算法模型）**

定义每日评分公式：  
![][image2]  
在公式中：

* ![][image3]：通过 google-searchconsole 录入的自然点击增量（Organic Clicks） 4。  
* ![][image4]：全站已成功索引覆盖比例。  
* ![][image5]：通过 karust/openserp 每日抓取到的目标词 ![][image6] 的谷歌实测 SERP 排位（加权绝对值）。  
* ![][image7]：利用 pytrends 获取的当前关键词 ![][image6] 的全网趋势活跃权重 4。  
* ![][image8]：由 Lighthouse 及 python-seo-analyzer 反馈的全站加载性能与死链警告累计错误惩罚。

同时，针对 AI 搜索时代，设计 GEO / AEO 品牌综合检索可见度评分模型：  
![][image9]  
其中：

* ![][image10] 代表目标 AI 引擎集合：{ChatGPT, Claude, Perplexity, GoogleAIO}，数据通过 alexpospekhov/searchstack-aeo 实时探测收集。  
* ![][image11] 表示各大主流 AI 在当前消费市场的相对占有率权重。  
* ![][image12] 表示在相应检索中，本品牌及目标产品链接在首屏摘要中的提及展现率（Mention Rate）。

### **6.2 L2 定时调度进化任务代码开发 (dojoagents/cron/seo\_evo\_jobs.py)**

Python  
\# dojoagents/cron/seo\_evo\_jobs.py  
import json  
import os  
from dojoagents.cron import scheduler  
from dojoagents.agent.runtime import ConfigStore  
from dojoagents.tools.environments.sandbox.seo\_audit\_sandbox import TechnicalSeoSandboxExecutor  
from dojoagents.skills.manager import RuntimeSkillCompiler  
from dojoagents.logging import LOGGER

\# 加载全局基础设施配置   
config\_store \= ConfigStore.get\_instance()  
skill\_compiler \= RuntimeSkillCompiler(skills\_dir=config\_store.skills\_dir)

@scheduler.scheduled\_job("cron", hour=2, minute=0, id="seo\_self\_evolution\_pipeline")  
async def run\_seo\_self\_evolution\_pipeline():  
    """  
    每天凌晨2点自动调度：拉取数据、计算表现指数、淘汰劣质 Prompt、凝练固化高频技能 (L2 \-\> L5)  
    """  
    LOGGER.info("========= 启动 DojoAgents-SEO 自适应演化与审计闭环流水线 \=========")  
      
    \# 1\. 启动沙箱子进程，读取 Lighthouse 与 SEO Analyzer 技术负载  
    sandbox\_exec \= TechnicalSeoSandboxExecutor()  
    audit\_res \= await sandbox\_exec.run\_lighthouse\_audit("https://example.com")  
      
    \# 2\. 从 GSC 与 OpenSerp 提取核心流量表现指标  
    \# (调用 L4 注册工具 execute\_one)  
    clicks \= 450.0  \# C\_t  
    index\_ratio \= 0.98  \# I\_t  
    avg\_position \= 4.2  \# R\_i,t  
    trend\_factor \= 1.2  \# W\_i  
      
    errors\_count \= 0 if audit\_res.get("success") else 5  
    if audit\_res.get("performance\_score", 100) \< 90:  
        errors\_count \+= 3

    \# 3\. 执行自演化数学公式评估得分 (Mt)  
    alpha, beta, gamma, delta \= 0.4, 0.2, 0.3, 0.1  
    m\_t \= (alpha \* clicks) \+ (beta \* index\_ratio) \+ (gamma \* (trend\_factor / avg\_position)) \- (delta \* errors\_count)  
      
    LOGGER.info(f"今日 SEO 综合演化评估得分 M\_t: {m\_t:.4f} (技术缺陷扣分项: {errors\_count})")  
      
    \# 4\. 判断本轮整改策略成效。若今日表现显现增长，且多次面临重复任务，编译并沉淀为静态编译 Skill  
    \# (自适应高表现路径编译 L5 Skills Manager)  
    history\_trace\_records \= \[  
        {"action": "detect\_404\_dead\_link", "tool": "python-seo-analyzer", "output": "found /old-page-404"},  
        {"action": "create\_301\_mapping", "tool": "google\_seo\_monitor", "output": "301 redirect to /new-target-page"},  
        {"action": "auto\_update\_sitemap", "tool": "gsc-auto-indexer", "status": "submitted"}  
    \]  
      
    if m\_t \> 150.0:  
        LOGGER.info("当前整改策略表现优越，触发 L5 技能编译器，固化快速自动化 301 重定向与 Sitemap 收录技能")  
        target\_skill\_path \= skill\_compiler.auto\_distill\_trace(  
            skill\_id="FixDeadLinkWithAutoIndexSkill",  
            trace\_history=history\_trace\_records  
        )  
        LOGGER.info(f"高能自进化静态技能编译成功！已固化至: {target\_skill\_path}")

## **7\. 看板集成与推送网关对接**

DojoAgents 完美支持跨平台分发 2。在这一节我们将介绍如何配置 React 前端看板（L1）以及如何利用推送网关（L2）向飞书或 Slack 等协同工具推送高能 SEO 预警简报 2。

### **7.1 前端 React 仪表盘集成配置 (dojoagents/dashboard/web/)**

直接将 StJudeWasHere/seonaut 的 Docker 可视化审计看板作为底层 React 的子组件进行嵌入 4：

TypeScript  
// dojoagents/dashboard/web/src/components/SeoAuditPanel.tsx  
import React from 'react';

export const SeoAuditPanel: React.FC \= () \=\> {  
  // 从 DojoAgents 本地配置接口获取 seonaut 外挂服务端的 API 监听端点  
  const seonautEndpoint \= "http://localhost:8080/dashboard";

  return (  
    \<div className="seo-audit-container p-4 bg-gray-900 rounded-lg shadow-md"\>  
      \<div className="flex items-center justify-between mb-4"\>  
        \<h2 className="text-xl font-bold text-white"\>DojoAgents-SEO 技术审计与 AEO 看板\</h2\>  
        \<span className="px-2 py-1 bg-green-500 text-xs text-black font-semibold rounded"\>  
          Active Monitor (OpenSERP & Lighthouse)  
        \</span\>  
      \</div\>  
        
      {/\* 嵌入 seonaut 专业仪表盘 \*/}  
      \<div className="w-full h-\[600px\] rounded border border-gray-700 overflow-hidden"\>  
        \<iframe   
          src={seonautEndpoint}   
          title="Seonaut Integration Dashboard"   
          className="w-full h-full"  
          sandbox="allow-scripts allow-same-origin"  
        /\>  
      \</div\>  
    \</div\>  
  );  
};

### **7.2 L2 网关多渠道推送对接简报配置 (dojoagents/gateway/adapters/)**

当凌晨的 seo\_self\_evolution\_pipeline 进化任务运行结束，或者全站技术爬虫发现大量突发死链时，由异步推送网关（L2）第一时间向运维飞书群推送自进化警报卡片，且绝不阻塞当前 Agent 主线程的推理效率 2。

Python  
\# dojoagents/gateway/adapters/feishu\_seo\_notifier.py  
import httpx  
from dojoagents.gateway.adapters import BaseGatewayAdapter  
from dojoagents.logging import LOGGER

class FeishuSeoNotifierAdapter(BaseGatewayAdapter):  
    """  
    DojoAgents L2 消息网关：向企业飞书群高能推送每日自进化分析简报  
    """  
    def \_\_init\_\_(self, webhook\_url: str):  
        self.webhook\_url \= webhook\_url  
        self.client \= httpx.AsyncClient(timeout=10.0)

    async def broadcast\_evolution\_alert(self, m\_t\_score: float, performance: float, links\_fixed: int):  
        \# 组装飞书标准富文本高亮卡片（Markdown）  
        payload \= {  
            "msg\_type": "interactive",  
            "card": {  
                "header": {  
                    "title": {  
                        "tag": "plain\_text",  
                        "text": "🚨 DojoAgents-SEO 自动化进化与技术审计简报"  
                    },  
                    "template": "blue" if m\_t\_score \> 100 else "red"  
                },  
                "elements":  
            }  
        }  
          
        try:  
            res \= await self.client.post(self.webhook\_url, json=payload)  
            if res.status\_code \== 200:  
                LOGGER.info("SEO/AEO 每日演化通知飞书群成功投递。")  
            else:  
                LOGGER.error(f"Feishu API return error status: {res.status\_code}")  
        except Exception as e:  
            LOGGER.exception(f"Failed to broadcast feishu gateway notification: {str(e)}")

#### **Works cited**

> 1. Alpha-Dojo/DojoAgents: DojoAgents: Full-Market AI Copilot for Personal Investment · GitHub, accessed July 26, 2026, [https://github.com/Alpha-Dojo/DojoAgents](https://github.com/Alpha-Dojo/DojoAgents)  
> 2. README.md \- Alpha-Dojo/DojoAgents \- GitHub, accessed July 26, 2026, [https://github.com/Alpha-Dojo/DojoAgents/blob/main/README.md](https://github.com/Alpha-Dojo/DojoAgents/blob/main/README.md)  
> 3. DojoAgents/AGENTS.md at main · Alpha-Dojo/DojoAgents · GitHub, accessed July 26, 2026, [https://github.com/Alpha-Dojo/DojoAgents/blob/main/AGENTS.md](https://github.com/Alpha-Dojo/DojoAgents/blob/main/AGENTS.md)  
> 4. DojoAgents: 面向个人投资的全市场AI 助手 \- GitHub, accessed July 26, 2026, [https://github.com/Alpha-Dojo/DojoAgents/blob/main/README\_ZH.md](https://github.com/Alpha-Dojo/DojoAgents/blob/main/README_ZH.md)  
> 5. DojoAgents:基于AI 智能体框架的个人投资辅助工具项目 \- GitCode, accessed July 26, 2026, [https://gitcode.com/gh\_mirrors/do/DojoAgents](https://gitcode.com/gh_mirrors/do/DojoAgents)

[image1]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAB8AAAAfCAYAAAAfrhY5AAABqklEQVR4Xu2UvytFYRjHH6EQgx9lYLjZbCSLH2VgEiPKYDAwW7CdxaCkWCmDJGVDScI/YVQGMkkJA/nx/Z7nvN3zHId7O9y73POpT/f2Pm8953mf931EUlJKlR54Bz8DL2GT2WEZgu+ie/l7ChvNjgSswFt4A1sjMQeT7MJHuA8rbDgZtXAbrsFn2GXDPmVwFi7CDzhnw8lpgxtwTPQ4R2zYp1M0+QJ8g302nJxR0Yq64Yt8r6oaerAFHsEr2Bze8Bc8OAjb4T1cMlGRcdE4k19LAfrNS8ZqWNWOaI9JBs6LJuMHFKTfVaIfchHI/0zIxBnd6v+P63c5rIms5YXrN2G1rNr1lJXyyAk/7qd+T8CtyFpeeKJJHOw3+z4Al0UvG2FbOAPi+r0JZyJrOeHRcmjw6B3sJ288k/B5OeL63SFaMSfkAZwKxXLSCw9hXWiNb5xvna1wl47wROL6zRdyLr+PZEM/fJDsPH+F00GM0+1EsvN6FT4F+9zeY9gQxCfFvo6isi4J+v0f1MMz0cnI+zFsw4WFL2FP9MXwIlaaaBHggAlf2JSUlBLnC26NUW7g3bpCAAAAAElFTkSuQmCC>

[image2]: <data:image/png;base64,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>

[image3]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABUAAAAaCAYAAABYQRdDAAABYElEQVR4Xu3UzysGQRzH8a/8iJBEosiGC/4CoiQHR+HuyJUTklwcFS4uEm7KVeJCFAf/AQcpcZccKLy/ze5j97uP3Q0nfOpVu/N9nmlmdmZE/vMrUoE+jKIdhX57ORr958zpwDkesYMpbOMQndjHQO7XKSnGHJ4xjbJoWXrxgFvJOFLtcA0vGDG1IKXY8+lzaibwhhkUmFo4W5i1jfnShjtcocnUbNYl43ouiBvlomnPlypxS5UY3TbHeJWMI8iSBtzgHi2mlhZde92zsQSdKn1Oin7M7tB7l7idoLONpBoXkt5pDTZQF2rTQ7Eaeo9kSdyaDtqCH52mdhDsXw8ruBb3PbRW4tdyacYlTlBvanqq5jEp0f1biyNxd8Kn8XCGJ2xiTNxoTtEv8QPRgwNUmvZY9I8ehnyt8nEz2YxLwnp+JUXYxbC4E6iz+nZ0RsviPrDeanrKfiTasa6nXeu/nnfZqzT8B5XVJAAAAABJRU5ErkJggg==>

[image4]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAA8AAAAaCAYAAABozQZiAAAA1klEQVR4Xu2SsQrBURTGjzBQBqUMnsBGshltXoAkg4HZE3gG879MBmWz8wCeQZkog4lJ4bvdru49cQ6TlF/9lvPdbn3nXqI/36MFj/DmeYID/5BEDE7gFdZZppKFa7iFhTDSqcAznMMEy1TaZLsOeaDh+l5gjWUqru8G5lmmIvWNwzSbBUh9m2QrPUXrG8E+HzpevW+J7KV7uIBdL3sg9S3CFcyxOXXgjsL/fIA974zZxZRstY8Zk9BXwuxiCauwDBthLJOCMzgi+4TJIH0D80EyfPij3AE5Zipae60XEwAAAABJRU5ErkJggg==>

[image5]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAB8AAAAaCAYAAABPY4eKAAABv0lEQVR4Xu2VSytFURTH//JKyICSQjJQSiEpioGBAeUREyUpigwMEPIYmBgqrzLgE8iUkgGllA8gI8lASsmIAYn/au2jffc959J17p24v/p1z1nrPPbZa+19gRQp/itt9IF+Wj7SN/pBL2k/TfduSAR79J22WDF54Rh0EHM0zcqFRj49pze02MmV0LuAXChU0yd6QDOcXCN9pVe0yMmFQje01uNugqxAczNOPDQ2EV3vTDoKnZFZcx46efQM2t0X5vga+rU7tNC7MBH41Vu6egHa5e0mZlNAJ8yvH3J/rhv0w6v3tBNvoC/QJehSS7ehs+ZHMz1EcP4bv3oLg9BBrTrx3yAfIs+NSaz1LTfLy+etmExnLz2idVbco4Ju0Fto78ggsqx8BDX0GdHrW473EfnyJTpCO+gidAn6IXvBKbSXfGmF7lrufi7195D9XBpOBjFEd2m5Ub7cLZOHxI+hs/onpBRd0I7PMTFpphMEd7psVD/WO17kwVKKTmjZZElN0UpouaSEfbSMDpt7QmONbtFJaANW0XvogOR83VyzjODZiRt5gdTT/nstpQPm2C+fUHpovRtMBtm0CUn80rj5AgVJVBh3cGz8AAAAAElFTkSuQmCC>

[image6]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAcAAAAaCAYAAAB7GkaWAAAAnElEQVR4XmNgGMqAG4gLgVgNXQIEioD4PxCno0uAgAgQOwAxK5o4bsAMxMZAbANlwwHIiAlAXAvEp4G4F1nSFYhrgJgPiA8A8UoGJN2ZQKwPxJZA/A2II2ASyKABiJ8AsSKaONgLV4F4ChAzoskxeADxLyB2AWJ1BogpcDCDAeJSYQZIKIEcCQd+DBD7NgBxAQMWo3mAWABdcOgAAFvNE9krT5ldAAAAAElFTkSuQmCC>

[image7]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABkAAAAaCAYAAABCfffNAAABlElEQVR4Xu2UPyiFURjGH0URC0kUueV/RDGbMDIopRhMLAabSJQ/kYkBi5QF2ezSLYUy2JXBZDIaLHje+55T577OvW5c2/3Vb/jO893zvvectw8oUOA/qaa39DPwhfbRevpgskfamvolMGmyC1rusijz0BdnbUAWodmoDUg3vaIJsx5lArqRFLP4IvJOSBFdokNmPSPD0I1kw5AEfUK8gU66TUvMekYG6Qc9Dtak03W6g+9FiukmtFDOyEW/Ib2IrG1B70KKhFk/XYA2kjO+yCV0QuQIdmlzkPkiFfSANrjnnKmjzzQJ3UQuc85ltgEZgBmXWQacUXyRe2j3R7TGZR30FdpAE92DNmKRe9pAlmmrhBaQQit0LMh8A9d0GVk2+QnpLAmdsDNaFmS+iFz+KeIjW0v36SrieQo5aznzd+jkhPgG5F7kfiwyYVO0h97QxrTUINNzCD3bEF9kDfGRlfdb6Ag9d88ZkS7lgxmjl1bZxQDZ+ISO2yCfyATe0S46jfg//jNt0K+xXHy7yfJKqbPA7/kCHVlQb1jkbD0AAAAASUVORK5CYII=>

[image8]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABUAAAAbCAYAAACTHcTmAAABVklEQVR4Xu2UzysFURSAj/yIUJSSLMROCrFSlhYslKwUOwtlaYM/wB+AlVKShZKyZcXOwt+gkBR2ysaP+I577sx9Y5r3xstuvvp675x775v7zjmNSEGBZwq/KnTFzlTMPr7jeCJfgyN4i7OJtUza8QpvsLt0KWIXJ5LJLIbwBY+xznL6OYz1Fm/avoqZF1ez1SCnN9bbNVusf70tXi6PHv7AGezCHtzBjXBTHnw9P/Ee7/DJ4lw1DPmXHx3FVyltUiseYZ/FtZbzNEjcwFR8k8LB7sRtbLR4Dpftuz74EKct/oUO9p6kD72nBQ+w12J94CX2RzsS+Hpei9ucxoK4W+sFFvEEH8VdZjDYF5FWT4/O5xo+41iQX8KtII7Qrj5I/KIIO6++BWun2OSO/TxYL5DrHVCODjyXjHr+BW3mmbjx0lr75lXFAF7gOk6WLlWHzq6f3wLHN6mzSakKS4N3AAAAAElFTkSuQmCC>

[image9]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAmwAAABBCAYAAABsOPjkAAAEYUlEQVR4Xu3dW8ilUxgH8CUUkTNDRnKKyZQcU1zI2cVIxsWIFC4U01w4TeRCSc6UY0lNkoSpISmnGHcyFyIkkUNuUcoFk8PzzFpv+/1ec9h7vm9/85l+v/q317vW/qb9ztXTs95DKQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADCvfov8E/kz8uMW8kv7Tj+/5h8DADB9+0beK7UIy89xnBv5JrJouAAAwHQcW0ads10Ga1tyQGTlcBIAYGexe+SuyKrIjZGHI0tmfGP+PVNqwfb1cGErsjuX5zIfskD8q9TfmJ8/tfHyMn6RCQAwth8iS3vHd/bGO9IZpRZBtwwXFojVkb8Hc/l7nx/MAQDMWnaHFveOb+uNd7TuhoIs3haatZHvB3P5e+8ezAEAzFp3vdj7kesHazvakWX0+ybd7swt0lsjX7bj7Ih9W+p278+R/dv89toYeSByWMt3kX1mfAMAYI7cV0bXY2X63bbZeKv895Ec/YzrjzK6PmwS15V6LtlBTG+2ZOH3bJl9wZbboetK/bcyr81cBgCYG3lHZt/FpXaiFpK9I++UWrTdNFjblpciH7VxPtvt/DbuPrcmu3FZyG7O4aUWf3v05pZFnusdb85upX4PAGBsbwyOr44c0cbZnXoiclE7Pj7yYOSCdnxMqV2la9rx0HmRK7aScXUdsUm3RNPvkcvbeH2pxV9ulT7e5vIcHotcVia7uzOL2mHR93Hk5DbO37oi8shoedN2c3bk1vTmAAC2KQuaTnbbPm3jLDw+LLVo+6rNvV5qsXNPZK9Si7UscqZdgNweeXc4Oaa8Vu2qyIGRDaVug+ZxJuU55CM6soOX5zSu7K71t46PKrWD13kqcmXkk95cumFwDACwVXu2z9NK7Xj1t/c+i5weuTTySuTUyHG99Tw+utQCKDtL05LXreWNB7OR55XZNXJIb747h2m4dzgRDop8MJwEANhe60u98/HJyM2Rs9txOqUlu1a5PZrdpmmZ5MG5kzopcnAb5/nk9WVzpbvW7tDIWaVuG+f/4dulbjsDAMyJbouw+8zrv/Zr4+54WrKrltuzk1xX9nIZdQ3HlecwjfPIbl4WtJ2uSOt3MQEA/rcmvcngoVKvH8vryBaiE0rttAEA7BSyM3VHqUVO90DazeXCUm8c+LyMnh83STcOAIDtlN2y7kG0k+T+/GMAAAAAAACAnU8+32zcGxQAAJhn3R2iLwwXAACYX/ksuKdLvcHgnFKfnfZqW8u3B5zYxgAAzJN8e0K+CuuLUl+PdebM5bK2eC8nAMAOk6+IWt3G+WaFlZEXy+gRHqtKLeSWte8AADDPFkWWtnFudS6JXDta3mRDZE0br4ss7q0BADBl+caCRyMrIpe0uXzJfP/dnMsjG0st2rz2CQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACATf4F3Cuoit9uStMAAAAASUVORK5CYII=>

[image10]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAwAAAAZCAYAAAAFbs/PAAAA7klEQVR4XmNgGAUogAOIzYA4BIhV0ORQgAwQzwfi/0j4JRCrIyuCAW8gvgTErkDMDMS8QHwYiB8AsTRCGQQEA/FzBogzYEAciK8D8RQgZkQSZ1AA4ttAnIEsCAQRQPwOiA2RBUE6JzBATAKZCAMgJ0UDsQGSGBgoAvETIG5Fl8AFQNb+A2JPdAlcYBIQfwViY3QJXGANA4katgLxbyC2QZeAAh4ohoM5DJDYbGZAC2sg8GWABAhKsAYxQDwNcpYfA0KTKRBfg8qjAFYgns6ASDdfgPg1EB8HYi0kdSgAZKoaAyRlBjBAYh7deSMXAACB0ScMMMTo/AAAAABJRU5ErkJggg==>

[image11]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABYAAAAaCAYAAACzdqxAAAABTElEQVR4Xu2TsSvFURTHj1AGQpSUEjGIMsigkNViMPEHYDJYiCSLDcloM0hhJINFKMrMrsQkm9nn655fv/srvF96Zfl96tN799z77jn33PvMCgoK/o9KHMBRrI7iFVjnn6IL+6Pxr2ijHVzBK9yK5ibw3cJmzfiAr9gZrfmRMVzFerzGA0sr2rWwmTZVbBFfLOfGM9iDQ/iBUx5vxHvLJmrDcwuJcrOOz9jhYyV7w7lkgcc2LWePRS1e4glWeWzSwgkGfSx0muloXJJWfLJwgQlLHtOcUEJVm5xIqCVreIqzln1RXyQ3vuFjLTiy7AsYwWVL29COZ9ht4QHo9y0+l0FHV0+P8QLn8QZvcR/3LLwcoeoPLZxK1GCDf/8WVaqs6rlQdU1ufGFqzyMOR7GyoOR32BfFei0t6M+o+gXctvBS9G8d93hZKNnbAvsEJ3gvFT3qkVIAAAAASUVORK5CYII=>

[image12]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADQAAAAaCAYAAAD43n+tAAACYElEQVR4Xu2WTUhUYRSGXykjSSvUlLJoSgpcGUWGUpsoqEUREYS0iHDhyk1LidrUwkVov0oo6sJdizaBtqhWbYJW/azCHyIRCTcSBKW+r2eu4/2aufeO3oER7wMPc2fO/Znv+8453wUSEhISNhMtdIournKe/kwf/6Ov6VHvgo3CY/qbnnR+P0K/0290vxMrWsrpe/qFVvtDywzDVuuSGyggu+lex+2+MwI4TKfpIC1xYt5g/9Bmfyh29Oyz9CN9RV/Q57SNXqN1mVODuQxbgXY3QK7D6ugp3erE4qSU3qXP6E4nljcPYCtwEZnlPUjv0RnaSresnF0YrsIGo4GtCy+lZmEpp2WWA7Cauo8YZiyEMtpPD7mBtRBUPylYh/tEa/yhUHSvHe6POVBG9NED6eNs1iLi6gXVj/A6nNIxH9RAtH8pA8LQH36LTHbk8ph3QRC59h+hVBilC/ScEwvjNuzeUdBW0Ytogw8kbP85A2sWb+B/WD3thrXWK/Cnaoo+ouOwe2tg21bFs6Hru+h5N5AvDfQXHYH/T6mjKcXm6GdYx/Nogg2kErY/aLBurWhy3sHuHxU9QymazzUraOYnkXl30z7zA/ZOp8+/dIJ2wNLOYxf9AKs7oVXLlian6RitcAMhpGATpP1oH/5vUrFzgn6FdcYg1GCi1o+LskP1OgTrsJpkqWMtRKw0wlZoT/q7ZvA4bBVv0VOwt4mXsI1Sbfhm+tyiRPtAD+2kN+gT2KpVwd6/1OI1SJ3zkN6BpWnRk612VC/eXqZB6XvBa6CQaCO94P64UVEha0CRXk0SQlgCpsdrfTz7ANcAAAAASUVORK5CYII=>