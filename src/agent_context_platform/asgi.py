from agent_context_platform.runtime import create_runtime_app


# ASGI server 只需要导入 app；数据库、Session、embedding provider 的装配都在 runtime.py。
app = create_runtime_app()
