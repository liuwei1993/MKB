# MKB · PubMed 医学问答

基于 PubMed 文献检索 + PMC 开放获取全文 RAG + 百炼大模型的网页版医学知识问答。

## 功能

1. 将中文问题改写为英文 PubMed 检索式  
2. 检索约 100 篇相关文献并拉取摘要（含 PMCID / DOI）  
3. 对可获取的 PMC Open Access 全文分块，经 embedding 检索 top-k 段落  
4. 大模型基于检索段落流式综合作答，并标注 `[PMID:…]`  
5. 页面依据文献优先跳转 PMC 全文 / DOI / PubMed  
6. 支持多轮追问：历史以摘要和最近几轮摘录参与检索词改写；换题不会带上旧主题；证据按轮重新检索。缩短、翻译或换说法时不重新检索  

无 OA 全文时自动回退摘要；embedding 失败时回退整批摘要作答。刷新页面或点「新对话」会清空上下文。

## 配置

复制环境变量模板并填写密钥：

```bash
cp .env.example .env
```

必填项：

| 变量 | 说明 |
|------|------|
| `LLM_MODEL` | 推荐 `deepseek-v4.1-flash` |
| `LLM_API_KEY` | 百炼 API Key |
| `LLM_BASE_URL` | 如 `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `EMBEDDING_MODEL` | 默认 `text-embedding-v3` |
| `NCBI_EMAIL` | NCBI 联系邮箱 |
| `NCBI_API_KEY` | NCBI API Key |

可选（有默认值）：`TARGET_PMIDS`（100）、`FULLTEXT_MAX_ARTICLES`（10）、`RAG_TOP_K`（12）、`CHUNK_SIZE`、`CHUNK_OVERLAP`、`FULLTEXT_MAX_CHARS`。

## 启动

后端（默认 `http://127.0.0.1:8000`）：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

前端（默认 `http://127.0.0.1:6173`，已代理 `/api`）：

```bash
cd frontend
npm install
npm run dev
```

浏览器打开前端地址即可提问。

## 健康检查

```bash
curl http://127.0.0.1:8000/api/health
```

## 发布到服务器

一键构建前端并部署到公司机（地址见本地 `.server-info`，目录 `/data1/mkb`，对外端口 **9400**）：

```bash
./scripts/deploy.sh
```

访问：`http://<公司机地址>:9400/`

可选环境变量：`REMOTE`、`REMOTE_DIR`、`PORT`（主机默认见 `.server-info`）。
