"""DSFlow：数据科学项目全周期追踪平台。"""

__version__ = "0.31.0"


def start_run(step: str, **kwargs):
    """开始记录一次运行，见 dsflow.tracking.sdk。"""
    from .tracking.sdk import start_run as _start

    return _start(step, **kwargs)
