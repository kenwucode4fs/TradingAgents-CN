"""
tests/portfolio 集成测试的本地环境补全（同构自 tests/factor/conftest.py）

背景：仓库根目录的 `.env` 是"最小化配置"（MONGODB_ENABLED=false，未配置账号密码），
用于不依赖数据库的本地开发；而本地通过 docker-compose 启动的 `tradingagents-mongodb`
容器要求账号密码鉴权（对照 docker-compose.yml 中 MONGO_INITDB_ROOT_USERNAME/PASSWORD）。

pydantic-settings 读取配置时，进程环境变量优先于 .env 文件，因此这里用
`os.environ.setdefault` 在导入 app.core.config 之前补上本地容器的默认账号密码，
使 `./venv/bin/python -m pytest tests/portfolio -m integration` 可以直接连上本机的
mongodb 容器。若外部已经设置了这些环境变量（如 CI/容器内运行），则不会被覆盖。
"""
import os

os.environ.setdefault("MONGODB_HOST", "localhost")
os.environ.setdefault("MONGODB_PORT", "27017")
os.environ.setdefault("MONGODB_USERNAME", "admin")
os.environ.setdefault("MONGODB_PASSWORD", "tradingagents123")
os.environ.setdefault("MONGODB_AUTH_SOURCE", "admin")
os.environ.setdefault("MONGODB_DATABASE", "tradingagents")
