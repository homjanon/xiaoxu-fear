#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XXFI 网络调用通用工具：指数退避重试 + 随机间隔 + UA 轮换
===========================================================

用于 fetch_market_akshare / fetch_history_baostock 等取数模块，
降低因网络波动导致的临时失败，以及批量调用触发反爬的概率。

注意：本模块的「重试」仅对临时性网络错误有效；
      对东方财富 IP 黑名单（Server RST）无效，该场景需换 egress IP（代理）。
"""
import random, time, functools
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from urllib3.exceptions import NewConnectionError, MaxRetryError, ProtocolError
from requests.exceptions import ConnectionError as RequestsConnectionError

# ---- 随机 User-Agent 池（降低批量请求时被反爬识别的概率） ----
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]
def random_ua():
    return random.choice(UA_POOL)


# ---- 随机间隔（模拟人类浏览节奏） ----
def jitter(min_s=0.5, max_s=2.0):
    """在两次请求之间睡眠随机秒数，降低连续调用触发反爬的概率。

    日常取数（每日 3-5 次调用）：min_s=0.3, max_s=1.0
    历史回溯（baostock 逐股 5000+ 次）：min_s=0.05, max_s=0.3
    """
    time.sleep(random.uniform(min_s, max_s))


# ---- 指数退避重试装饰器 ----
def retry_on_network(max_attempts=3, min_wait=4, max_wait=30):
    """对东财等网络接口的临时性错误（RemoteDisconnected / ConnectionError）
    自动重试，等待时间指数级增长：4s → 8s → 16s。

    共 max_attempts 次尝试（含首次），全部失败后抛出原始异常由调用方降级处理。
    """
    # 东财服务端 RST / 连接超时 / 代理错误 等网络层错误一律视为可重试
    network_errors = (
        ConnectionError, RequestsConnectionError,
        NewConnectionError, MaxRetryError, ProtocolError,
        OSError, TimeoutError,
    )
    try:
        import http.client
        network_errors = network_errors + (http.client.RemoteDisconnected,)
    except Exception:
        pass

    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=2, min=min_wait, max=max_wait),
        retry=retry_if_exception_type(network_errors),
        reraise=True,
        before_sleep=lambda retry_state: print(
            f"[retry] {retry_state.fn.__name__ if hasattr(retry_state.fn, '__name__') else '?'} "
            f"attempt {retry_state.attempt_number}/{max_attempts} failed, "
            f"retrying in {retry_state.next_action.sleep:.0f}s..."
        ) if retry_state.attempt_number > 1 else None,
    )


# ---- 快速重试（仅 2 次，适合轻量调用） ----
def retry_fast(max_attempts=2, min_wait=1, max_wait=8):
    return retry_on_network(max_attempts=max_attempts, min_wait=min_wait, max_wait=max_wait)
