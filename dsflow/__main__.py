"""`python -m dsflow …`：不依赖 PATH 上有 dsflow 可执行文件（hook 与被管项目里的命令都走这里）。"""

from .cli import app

app()
